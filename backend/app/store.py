"""Vendor runs kept as one JSON file each. Small, local, nothing exposed beyond the API."""
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import config

RUNS_INDEX_DIR = Path(os.environ.get("CTP_VENDOR_RUNS_DIR", config.REPO_ROOT / "data" / "vendor-runs"))


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _path(run_id: str) -> Path:
    if not run_id.isalnum() or len(run_id) != 12:
        raise KeyError(run_id)
    return RUNS_INDEX_DIR / f"{run_id}.json"


def create(vendor: dict, checks: list[str]) -> dict:
    RUNS_INDEX_DIR.mkdir(parents=True, exist_ok=True)
    run = {
        "id": uuid.uuid4().hex[:12],
        "vendor": vendor,
        "requested_at": now(),
        "status": "queued",
        "pending": checks,
        "checks": [],
        "decision": None,
        "manifest_sha256": None,
        "finished_at": None,
        "approval": None,
    }
    save(run)
    return run


def save(run: dict) -> None:
    path = _path(run["id"])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(run, indent=2), encoding="utf-8")
    tmp.replace(path)


def load(run_id: str) -> dict:
    path = _path(run_id)
    if not path.exists():
        raise KeyError(run_id)
    return json.loads(path.read_text(encoding="utf-8"))


def recent(limit: int = 20) -> list[dict]:
    if not RUNS_INDEX_DIR.exists():
        return []
    files = sorted(RUNS_INDEX_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    runs = [json.loads(p.read_text(encoding="utf-8")) for p in files]
    return [{k: r[k] for k in ("id", "vendor", "requested_at", "status", "decision")} for r in runs]
