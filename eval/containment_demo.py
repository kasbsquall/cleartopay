"""Live containment demo, filmed for the video: one microVM with the vendor_site network policy.

It reaches the vendor's host, fails to reach anything else (a real site, the collection host and the
Inference API), shows that no key-like variable exists inside, then is destroyed and confirmed gone.
The same request is made from the VM first, so the refusal is clearly the microVM's.
Output is printed with timestamps, verbatim. Run on the VM from the repo root:  python3 eval/containment_demo.py
"""
import asyncio
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app import config  # noqa: E402
from app.sandbox import _gone, network_for  # noqa: E402

VENDOR = "pinecrest.45-76-12-143.sslip.io"
TARGETS = (f"https://{VENDOR}/", "https://example.com/", "https://pinecrest-collect.example/k",
           "https://api.vultrinference.com/v1/models")
FETCH = """
import sys, urllib.request
url = sys.argv[1]
try:
    with urllib.request.urlopen(url, timeout=8) as r:
        print(f"GET {url} -> HTTP {r.status}")
except Exception as e:
    print(f"GET {url} -> BLOCKED ({str(getattr(e, 'reason', e))[:70]})")
"""
ENV = "import os; names = sorted(os.environ); print(len(names), 'variables:', ' '.join(names)); " \
      "hits = [n for n in names if any(w in n.upper() for w in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD'))]; " \
      "print('key-like names:', hits or 'none')"


def say(text: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {text}", flush=True)


async def main() -> None:
    from microsandbox import Sandbox

    name = "ctp-demo-vendor-site"
    with urllib.request.urlopen("https://example.com/", timeout=8) as r:
        say(f"outside, on the VM itself: GET https://example.com/ -> HTTP {r.status}")
    say(f"create microVM {name}: 1 vCPU, 2048 MiB, egress allowed only to {VENDOR}")
    sandbox = await Sandbox.create(name, image=config.PROBE_IMAGE, cpus=1, memory=2048, max_duration=150.0,
                                   network=network_for((VENDOR,)), intercept_tls=True)
    try:
        for url in TARGETS:
            out = await sandbox.exec("python3", ["-c", FETCH, url], timeout=20.0)
            say("inside: " + (out.stdout_text or out.stderr_text).strip())
        out = await sandbox.exec("python3", ["-c", ENV], timeout=20.0)
        for line in (out.stdout_text or "").strip().splitlines():
            say("inside: " + line)
    finally:
        await sandbox.destroy(force=True, timeout=20)
    say(f"destroyed; still exists: {not await _gone(name)}")


if __name__ == "__main__":
    asyncio.run(main())
