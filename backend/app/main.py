"""HTTP API for the vendor file. Listens on 127.0.0.1 only; Caddy is the public face."""
import asyncio
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

from . import config, store
from .checks import CHECKS, OFFICIAL
from .checks.vendor_site import site_host
from .evidence import manifest_digest
from .models import Vendor
from .pipeline import decide, run_check

MAX_QUEUED = 5

app = FastAPI(title="ClearToPay", docs_url=None, redoc_url=None)
_one_vendor_at_a_time = asyncio.Lock()  # a 2 vCPU host runs one microVM per check, one vendor at a time
_queued: set[str] = set()


class VendorIn(BaseModel):
    legal_name: str = Field(min_length=2, max_length=120)
    state: str = Field(default="CO", pattern=r"^[A-Z]{2}$")
    website: str = Field(default="", max_length=200)

    @field_validator("website")
    @classmethod
    def public_host_only(cls, value: str) -> str:
        value = value.strip()
        if value:
            site_host(value)  # raises ValueError -> 422 for IPs, localhost and internal names
        return value


class ApprovalIn(BaseModel):
    approver: str = Field(min_length=2, max_length=80)


def _checks_for(vendor: Vendor) -> list[str]:
    names = list(OFFICIAL)
    if vendor.website:
        names.append("vendor_site")
    return names


async def _execute(run_id: str, vendor: Vendor) -> None:
    async with _one_vendor_at_a_time:
        _queued.discard(run_id)
        run = store.load(run_id)
        run["status"] = "running"
        store.save(run)
        try:
            for name in list(run["pending"]):
                rec = await run_check(CHECKS[name], vendor)
                run["checks"].append(rec)
                run["pending"].remove(name)
                store.save(run)
        except Exception as exc:  # fail closed: an unfinished file can never be clear to pay
            run["error"] = f"{type(exc).__name__}: {exc}"[:300]
        run["decision"] = "needs_human" if run["pending"] else decide(run["checks"])
        run["manifest_sha256"] = manifest_digest(run["checks"])
        run["status"] = "done"
        run["finished_at"] = store.now()
        store.save(run)


@app.post("/api/runs", status_code=202)
async def start_run(body: VendorIn) -> dict:
    if len(_queued) >= MAX_QUEUED:
        raise HTTPException(429, "Too many vendors waiting. Try again in a minute.")
    vendor = Vendor(legal_name=body.legal_name.strip(), state=body.state, website=body.website.strip())
    run = store.create(vendor.__dict__, _checks_for(vendor))
    _queued.add(run["id"])
    asyncio.create_task(_execute(run["id"], vendor))
    return {"id": run["id"]}


@app.get("/api/runs")
async def list_runs() -> list[dict]:
    return store.recent()


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> dict:
    try:
        return store.load(run_id)
    except KeyError:
        raise HTTPException(404, "No vendor file with that id.")


@app.post("/api/runs/{run_id}/approve")
async def approve(run_id: str, body: ApprovalIn) -> dict:
    run = await get_run(run_id)
    if run["status"] != "done":
        raise HTTPException(409, "Checks are still running.")
    if run["decision"] != "clear_to_pay":
        raise HTTPException(409, "Payment can only be released when every check is clear.")
    run["approval"] = {"by": body.approver.strip(), "at": store.now(), "simulated": True}
    store.save(run)
    return run


@app.get("/api/runs/{run_id}/checks/{check}/screenshot")
async def screenshot(run_id: str, check: str) -> FileResponse:
    run = await get_run(run_id)
    rec = next((c for c in run["checks"] if c["check"] == check), None)
    if rec is None:
        raise HTTPException(404, "No such check in this vendor file.")
    root = config.RUNS_DIR.resolve()
    path = (root / rec["containment"]["sandbox"] / "out" / "screenshot.png").resolve()
    if root not in path.parents or not path.exists():
        raise HTTPException(404, "Screenshot not available.")
    return FileResponse(Path(path), media_type="image/png")
