"""Print what OFAC and SAM return for a few vendors, to study near matches. Run on the VM."""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.checks import CHECKS  # noqa: E402
from app.models import Vendor  # noqa: E402
from app.pipeline import run_check  # noqa: E402


async def main(names: list[str], checks: list[str]) -> None:
    out = []
    for name in names:
        for check in checks:
            rec = await run_check(CHECKS[check], Vendor(name, "CO"))
            row = {"vendor": name, "check": check, "verdict": rec["verdict"], "reason": rec.get("reason"),
                   "records": rec.get("records") or rec.get("reading"), "verifier": rec.get("verifier")}
            print(json.dumps(row, default=str)[:1500], flush=True)
            out.append(row)
    Path("eval/results/probe-readings.json").write_text(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[2:], sys.argv[1].split(",")))
