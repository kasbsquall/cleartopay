"""Run checks for one vendor and build the evidence file. Anything uncertain fails closed."""
import asyncio
from types import ModuleType

from .checks import CHECKS, OFFICIAL
from .evidence import manifest_digest, record
from .models import CheckOutcome, Reading, Vendor, Verdict
from .sandbox import run_probe
from .verifier import verify


async def run_check(module: ModuleType, vendor: Vendor, verifier=verify) -> dict:
    spec = module.build(vendor)
    run = await run_probe(spec)
    second_reading = None
    extra: dict = {}
    if not run.ok:
        outcome = CheckOutcome(Verdict.ERROR, f"check did not complete: {run.error or 'no output'}", Reading(None))
    elif not run.destroyed:
        outcome = CheckOutcome(Verdict.ERROR, "sandbox was not destroyed after the check", Reading(None))
    elif hasattr(module, "assess"):  # untrusted pages: read by the agent, inspected for injection
        outcome, extra = await module.assess(run, vendor)
    else:
        outcome = module.judge(module.parse(run.page_text), vendor)
        second_reading = await verifier(module.NAME, vendor.legal_name, run.screenshot, outcome.reading.result_count)
        outcome = reconcile(outcome, second_reading)
    rec = record(module.NAME, spec.query, run, outcome)
    rec["verifier"] = second_reading
    rec.update(extra)
    return rec


def reconcile(outcome: CheckOutcome, second: dict | None) -> CheckOutcome:
    """The verifier can only send a check to a human, never clear it."""
    if not second or second.get("skipped") or outcome.verdict in (Verdict.HIT, Verdict.ERROR):
        return outcome
    if not second.get("agrees"):
        why = second.get("error") or f"it counted {second.get('result_count_seen')} results"
        return CheckOutcome(Verdict.REVIEW, f"the verifier read the screenshot differently ({why})", outcome.reading)
    if second.get("exact_match_seen") and outcome.verdict == Verdict.CLEAR:
        return CheckOutcome(Verdict.REVIEW, "the verifier saw an exact name match the parser did not", outcome.reading)
    return outcome


def decide(records: list[dict]) -> str:
    """Vendor-level call. Only an all-clean file is clear to pay; any hit blocks."""
    verdicts = {r["verdict"] for r in records}
    if Verdict.HIT.value in verdicts:
        return "blocked"
    if records and verdicts <= {Verdict.CLEAR.value, Verdict.VERIFIED.value}:
        return "clear_to_pay"
    return "needs_human"


async def run_vendor(vendor: Vendor, names: tuple[str, ...] = OFFICIAL) -> dict:
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
