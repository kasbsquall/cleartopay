"""Paths and runtime settings. Secrets come from the environment and never reach a sandbox."""
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SANDBOX_DIR = REPO_ROOT / "sandbox"
PYLIB_DIR = SANDBOX_DIR / "pylib"
RUNS_DIR = Path(os.environ.get("CTP_RUNS_DIR", REPO_ROOT / "data" / "runs"))
PROBE_IMAGE = os.environ.get("CTP_PROBE_IMAGE", "mcr.microsoft.com/playwright/python:v1.64.1-noble")
