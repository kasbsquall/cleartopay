"""Compare the screenshot verifier with and without reasoning on real captures. Run on the VM.

usage: python eval/verifier_budget.py <check>:<vendor>:<run dir>:<true count> ...
"""
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app import inference, verifier  # noqa: E402

SETTINGS = [
    ("sin razonar", {"chat_template_kwargs": {"enable_thinking": False}}, 1500),
    ("low", {"reasoning_effort": "low"}, 4000),
    ("normal 12k", {}, 12000),
]


async def ask(extra: dict, max_tokens: int, check: str, vendor: str, shot: Path) -> dict:
    text = verifier.PROMPT.format(source=verifier.SOURCES[check], vendor=vendor)
    body = {"model": verifier.MODEL, "temperature": 0, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": [{"type": "text", "text": text}, inference.image_part(shot)]}]}
    body.update(extra)
    started = time.monotonic()
    async with httpx.AsyncClient(timeout=200) as client:
        resp = await client.post(f"{inference.BASE_URL}/chat/completions", json=body,
                                 headers={"Authorization": f"Bearer {os.environ['VULTR_INFERENCE_API_KEY']}"})
    payload = resp.json()
    choice = payload["choices"][0]
    content = choice["message"].get("content") or ""
    found = re.search(r"\{.*\}", content, re.S)
    try:
        data = json.loads(found.group(0)) if found else {}
    except json.JSONDecodeError:
        data = {}
    details = payload.get("usage", {}).get("completion_tokens_details") or {}
    return {"seconds": round(time.monotonic() - started, 1), "reasoning": details.get("reasoning_tokens"),
            "finish": choice.get("finish_reason"), "count": data.get("result_count", "no JSON"),
            "exact": data.get("exact_match")}


async def main(specs: list[str]) -> None:
    rows = []
    for spec in specs:
        check, vendor, run_dir, truth = spec.split(":")
        shot = ROOT / "data" / "runs" / run_dir / "out" / "screenshot.png"
        for label, extra, max_tokens in SETTINGS:
            for _ in range(2):
                r = await ask(extra, max_tokens, check, vendor, shot)
                r.update({"check": check, "vendor": vendor, "setting": label, "true_count": int(truth)})
                rows.append(r)
                print(f"{check:8} {label:12} {r['seconds']:5}s razon={r['reasoning']} fin={r['finish']} "
                      f"cuenta={r['count']} (real {truth}) exacta={r['exact']}", flush=True)
    (ROOT / "eval" / "results" / "verifier-budget.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
