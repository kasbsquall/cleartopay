"""Run every case in eval/cases.json through the real pipeline k times and score it.

Run on the VM from the repo root:  python3 eval/run_eval.py --k 3
Raw per-run output and the summary go to eval/results/<timestamp>.json.
"""
import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.models import Vendor  # noqa: E402
from app.pipeline import run_vendor  # noqa: E402

CHECK_KEYS = ("ofac", "sam", "colorado")


def score_run(case: dict, result: dict) -> dict:
    got = {c["check"]: c["verdict"] for c in result["checks"]}
    expected_checks = {k: v for k, v in case["expected"].items() if k in CHECK_KEYS}
    return {
        "decision": result["decision"],
        "decision_ok": result["decision"] in case["expected_decision"],
        "dangerous_miss": result["decision"] == "clear_to_pay" and "clear_to_pay" not in case["expected_decision"],
        "false_alarm": result["decision"] != "clear_to_pay" and case["expected_decision"] == ["clear_to_pay"],
        "verdicts": got,
        "check_mismatches": {k: [v, got.get(k)] for k, v in expected_checks.items() if got.get(k) != v},
        "errors": [c["check"] for c in result["checks"] if c["verdict"] == "error"],
        "all_destroyed": all(c["containment"]["destroyed"] for c in result["checks"]),
        "seconds": round(sum(c["containment"]["seconds"] for c in result["checks"]), 2),
        "manifest_sha256": result["manifest_sha256"],
    }


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    count = lambda key: sum(1 for r in rows if r[key])  # noqa: E731
    return {
        "runs": n,
        "decision_correct": count("decision_ok"),
        "dangerous_misses": count("dangerous_miss"),
        "false_alarms": count("false_alarm"),
        "runs_with_check_errors": sum(1 for r in rows if r["errors"]),
        "runs_with_check_mismatch": sum(1 for r in rows if r["check_mismatches"]),
        "sandboxes_not_destroyed": n - count("all_destroyed"),
        "avg_seconds_per_vendor": round(sum(r["seconds"] for r in rows) / n, 1) if n else None,
    }


async def main(k: int, limit: int | None, groups: set[str] | None) -> Path:
    data = json.loads((ROOT / "eval" / "cases.json").read_text(encoding="utf-8"))
    cases = [c for c in data["cases"] if not groups or c["group"] in groups][:limit]
    rows = []
    started = time.monotonic()
    for rep in range(k):
        for case in cases:
            result = await run_vendor(Vendor(legal_name=case["name"], state="CO"))
            row = {"case": case["name"], "group": case["group"], "rep": rep, **score_run(case, result)}
            rows.append(row)
            flag = "ok" if row["decision_ok"] else "MISS"
            print(f"[{rep}] {flag:4} {case['group']:13} {case['name'][:38]:38} {row['decision']:12} {row['verdicts']}")
    summary = summarize(rows)
    summary["by_group"] = {g: summarize([r for r in rows if r["group"] == g]) for g in sorted({r["group"] for r in rows})}
    summary["wall_seconds"] = round(time.monotonic() - started, 1)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    out = ROOT / "eval" / "results" / f"{stamp}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"k": k, "cases_file_built_at": data["built_at"], "summary": summary,
                               "runs": rows}, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--k", type=int, default=1)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--groups", help="comma-separated: ofac_sdn,sam_exclusion,clean,tricky")
    args = parser.parse_args()
    groups = set(args.groups.split(",")) if args.groups else None
    print(asyncio.run(main(args.k, args.limit, groups)))
