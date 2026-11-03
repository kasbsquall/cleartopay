"""Fixed browser probe that runs inside a disposable microVM.

The backend writes /in/task.json and reads everything back from /out.
The model never writes code that runs here: a task is a list of steps
drawn from ACTIONS, with selectors chosen by the backend's check modules.

task.json:
  {"url": "https://...", "steps": [{"do": "fill", "selector": "#q", "value": "ACME"}, ...],
   "viewport": [1280, 900], "timeout_ms": 30000}

Outputs in /out: screenshot.png, page.txt, result.json.
"""
import base64
import hashlib
import json
import os
import subprocess
import sys
import time

from playwright.sync_api import Page, sync_playwright

IN_PATH = "/in/task.json"
OUT_DIR = "/out"
CA_PATH = "/.msb/tls/ca.pem"
ACTIONS = {"goto", "fill", "click", "press", "select", "wait_for", "wait_ms"}
MAX_STEPS = 12
MAX_TEXT_CHARS = 20000


def ca_spki_hash() -> str:
    """Base64 SHA-256 of the sandbox CA's public key, so Chromium trusts only that CA."""
    pubkey = subprocess.run(
        ["openssl", "x509", "-in", CA_PATH, "-pubkey", "-noout"],
        check=True, capture_output=True,
    ).stdout
    der = subprocess.run(
        ["openssl", "pkey", "-pubin", "-outform", "der"],
        input=pubkey, check=True, capture_output=True,
    ).stdout
    return base64.b64encode(hashlib.sha256(der).digest()).decode()


def load_task() -> dict:
    with open(IN_PATH, encoding="utf-8") as fh:
        task = json.load(fh)
    steps = task.get("steps", [])
    if len(steps) > MAX_STEPS:
        raise ValueError(f"too many steps: {len(steps)}")
    for step in steps:
        if step.get("do") not in ACTIONS:
            raise ValueError(f"action not allowed: {step.get('do')}")
    return task


def run_step(page: Page, step: dict, timeout_ms: int) -> None:
    do = step["do"]
    if do == "goto":
        page.goto(step["url"], timeout=timeout_ms, wait_until="domcontentloaded")
    elif do == "fill":
        page.fill(step["selector"], step["value"], timeout=timeout_ms)
    elif do == "click":
        page.click(step["selector"], timeout=timeout_ms)
    elif do == "press":
        page.press(step["selector"], step["key"], timeout=timeout_ms)
    elif do == "select":
        page.select_option(step["selector"], step["value"], timeout=timeout_ms)
    elif do == "wait_for":
        page.wait_for_selector(step["selector"], timeout=timeout_ms)
    elif do == "wait_ms":
        page.wait_for_timeout(min(int(step["ms"]), 10000))


def main() -> int:
    started = time.time()
    result = {
        "ok": False,
        # Names only: proves no credential reached the sandbox without echoing values.
        "env_names": sorted(os.environ),
        "requests_blocked": [],
        "steps_done": 0,
    }
    try:
        task = load_task()
        timeout_ms = int(task.get("timeout_ms", 30000))
        width, height = task.get("viewport", [1280, 900])
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=[f"--ignore-certificate-errors-spki-list={ca_spki_hash()}"],
            )
            page = browser.new_page(viewport={"width": width, "height": height})
            page.on(
                "requestfailed",
                lambda req: result["requests_blocked"].append(
                    {"url": req.url[:300], "error": (req.failure or "")[:200]}
                ),
            )
            page.goto(task["url"], timeout=timeout_ms, wait_until="domcontentloaded")
            for step in task.get("steps", []):
                run_step(page, step, timeout_ms)
                result["steps_done"] += 1
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
            page.screenshot(path=f"{OUT_DIR}/screenshot.png", full_page=False)
            text = page.inner_text("body")[:MAX_TEXT_CHARS]
            with open(f"{OUT_DIR}/page.txt", "w", encoding="utf-8") as fh:
                fh.write(text)
            result["final_url"] = page.url
            result["title"] = page.title()
            browser.close()
        result["ok"] = True
    except Exception as exc:  # reported to the backend, which fails closed
        result["error"] = f"{type(exc).__name__}: {exc}"[:500]
    result["seconds"] = round(time.time() - started, 2)
    with open(f"{OUT_DIR}/result.json", "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
