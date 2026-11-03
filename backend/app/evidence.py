"""Evidence records: what was searched, where, when, what the page showed, and its hash."""
import hashlib
import json
from pathlib import Path

from .models import CheckOutcome
from .sandbox import ProbeRun


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def record(check: str, query: str, run: ProbeRun, outcome: CheckOutcome) -> dict:
    blocked = run.result.get("requests_blocked", [])
    return {
        "check": check,
        "query": query,
        "verdict": outcome.verdict.value,
        "reason": outcome.reason,
        "result_count": outcome.reading.result_count,
        "records": [{"name": r.name, **r.detail} for r in outcome.reading.records],
        "url": run.result.get("final_url", ""),
        "captured_at": run.started_at,
        "screenshot_sha256": sha256_file(run.screenshot) if run.screenshot else None,
        "page_text_sha256": hashlib.sha256(run.page_text.encode("utf-8")).hexdigest(),
        "containment": {
            "sandbox": run.sandbox_name,
            "limits": run.limits,
            "allowed_hosts": list(run.allowed_hosts),
            "blocked_hosts": sorted({b["url"].split("/")[2] for b in blocked if "://" in b["url"]}),
            "env_names_in_sandbox": run.result.get("env_names", []),
            "destroyed": run.destroyed,
            "seconds": run.seconds,
        },
        "error": run.error,
    }


def manifest_digest(records: list[dict]) -> str:
    """One hash over every record, so any later edit to the evidence file is detectable."""
    canonical = json.dumps(records, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
