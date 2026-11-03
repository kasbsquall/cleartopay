"""Run checks for one vendor and build the evidence file. Anything uncertain fails closed."""
import asyncio
from types import ModuleType

from .checks import CHECKS
from .evidence import manifest_digest, record
from .models import CheckOutcome, Reading, Vendor, Verdict
from .sandbox import run_probe


async def run_check(module: ModuleType, vendor: Vendor) -> dict:
    spec = module.build(vendor)
    run = await run_probe(spec)
    if not run.ok:
        outcome = CheckOutcome(Verdict.ERROR, f"check did not complete: {run.error or 'no output'}", Reading(None))
    elif not run.destroyed:
        outcome = CheckOutcome(Verdict.ERROR, "sandbox was not destroyed after the check", Reading(None))
    else:
        outcome = module.judge(module.parse(run.page_text), vendor)
    return record(module.NAME, spec.query, run, outcome)


def decide(records: list[dict]) -> str:
    """Vendor-level call. Only an all-clean file is clear to pay; any hit blocks."""
    verdicts = {r["verdict"] for r in records}
    if Verdict.HIT.value in verdicts:
        return "blocked"
    if records and verdicts <= {Verdict.CLEAR.value, Verdict.VERIFIED.value}:
        return "clear_to_pay"
    return "needs_human"


async def run_vendor(vendor: Vendor, names: tuple[str, ...] = tuple(CHECKS)) -> dict:
    # Sequential on purpose: a 2 vCPU host runs one 1-vCPU microVM per check comfortably.
    records = []
    for name in names:
        records.append(await run_check(CHECKS[name], vendor))
    return {"vendor": vendor.__dict__, "decision": decide(records), "checks": records,
            "manifest_sha256": manifest_digest(records)}


if __name__ == "__main__":
    import json
    import sys

    result = asyncio.run(run_vendor(Vendor(legal_name=sys.argv[1], state="CO")))
    print(json.dumps(result, indent=2))
