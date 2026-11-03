"""One disposable microVM per check.

Each run: create the microVM with a per-source egress allowlist, CPU, memory and time limits,
run the fixed probe, read its output from the host, destroy it, then confirm it no longer exists.
No environment variable from the backend is passed in; the only extra variable is PYTHONPATH.
"""
import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .models import ProbeSpec

GUEST_PYLIB = "/opt/pylib"
GUEST_PROBE = "/opt/probe"


@dataclass(frozen=True)
class ProbeRun:
    sandbox_name: str
    ok: bool
    started_at: str
    seconds: float
    destroyed: bool
    limits: dict
    allowed_hosts: tuple[str, ...]
    result: dict = field(default_factory=dict)
    screenshot: Path | None = None
    page_text: str = ""
    error: str = ""


def _destination(host: str):
    from microsandbox import Destination

    if host.startswith("*."):
        return Destination.domain_suffix(host[2:])
    return Destination.domain(host)


def network_for(hosts: tuple[str, ...]):
    """Deny everything in both directions except HTTPS/HTTP to the listed hosts."""
    from microsandbox import Action, Network, NetworkPolicy, Rule, TlsConfig

    rules = tuple(Rule.allow(destination=_destination(h)) for h in hosts)
    policy = NetworkPolicy(default_egress=Action.DENY, default_ingress=Action.DENY, rules=rules)
    # Hostname rules need TLS interception; the proxy still verifies the real site's certificate.
    return Network(policy=policy, tls=TlsConfig(block_quic=True))


def _prepare_workdir(name: str, task: dict) -> Path:
    workdir = config.RUNS_DIR / name
    (workdir / "in").mkdir(parents=True)
    (workdir / "out").mkdir()
    (workdir / "out").chmod(0o777)  # the guest writes as root through the bind mount
    (workdir / "in" / "task.json").write_text(json.dumps(task), encoding="utf-8")
    return workdir


async def _gone(name: str) -> bool:
    from microsandbox import Sandbox, SandboxNotFoundError

    try:
        await Sandbox.get(name)
    except SandboxNotFoundError:
        return True
    return False


async def run_probe(spec: ProbeSpec) -> ProbeRun:
    from microsandbox import Sandbox, Volume

    name = f"ctp-{spec.check}-{uuid.uuid4().hex[:10]}"
    workdir = _prepare_workdir(name, spec.task)
    limits = {"cpus": spec.cpus, "memory_mib": spec.memory_mib, "max_seconds": spec.max_seconds}
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    clock = time.monotonic()
    error = ""
    sandbox = None
    try:
        sandbox = await Sandbox.create(
            name,
            image=config.PROBE_IMAGE,
            cpus=spec.cpus,
            memory=spec.memory_mib,
            max_duration=float(spec.max_seconds),
            network=network_for(spec.allowed_hosts),
            intercept_tls=True,
            env={"PYTHONPATH": GUEST_PYLIB},
            volumes={
                GUEST_PYLIB: Volume.bind(str(config.PYLIB_DIR), readonly=True),
                GUEST_PROBE: Volume.bind(str(config.SANDBOX_DIR), readonly=True),
                "/in": Volume.bind(str(workdir / "in"), readonly=True),
                "/out": Volume.bind(str(workdir / "out")),
            },
        )
        output = await sandbox.exec("python3", [f"{GUEST_PROBE}/probe.py"], timeout=float(spec.max_seconds))
        if not output.success:
            error = (output.stderr_text or output.stdout_text)[-500:]
    except Exception as exc:  # the caller fails closed on any error
        error = f"{type(exc).__name__}: {exc}"[:500]
    finally:
        if sandbox is not None:
            await _destroy(sandbox, name)
        else:
            await _remove_quietly(name)
    destroyed = await _gone(name)
    return _collect(name, workdir, spec, limits, started_at, time.monotonic() - clock, destroyed, error)


async def _destroy(sandbox, name: str) -> None:
    try:
        await sandbox.destroy(force=True, timeout=20)
    except Exception:
        await _remove_quietly(name)


async def _remove_quietly(name: str) -> None:
    from microsandbox import Sandbox

    try:
        await asyncio.wait_for(Sandbox.remove(name), timeout=20)
    except Exception:
        pass  # _gone() reports whether it is still there


def _collect(name, workdir, spec, limits, started_at, seconds, destroyed, error) -> ProbeRun:
    out = workdir / "out"
    result = {}
    if (out / "result.json").exists():
        result = json.loads((out / "result.json").read_text(encoding="utf-8"))
    page = out / "page.txt"
    shot = out / "screenshot.png"
    ok = not error and bool(result.get("ok")) and shot.exists() and page.exists()
    return ProbeRun(
        sandbox_name=name,
        ok=ok,
        started_at=started_at,
        seconds=round(seconds, 2),
        destroyed=destroyed,
        limits=limits,
        allowed_hosts=spec.allowed_hosts,
        result=result,
        screenshot=shot if shot.exists() else None,
        page_text=page.read_text(encoding="utf-8") if page.exists() else "",
        error=error or result.get("error", ""),
    )
