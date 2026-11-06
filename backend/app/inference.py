"""Vultr Serverless Inference, OpenAI-compatible. Only the backend holds the key; no sandbox ever sees it."""
import base64
import json
import os
import re
import time
from pathlib import Path

import httpx

BASE_URL = os.environ.get("INFERENCE_BASE_URL", "https://api.vultrinference.com/v1")
MIN_TOKENS = 1000  # below this, reasoning models can spend everything thinking and return nothing (D17)


class InferenceError(RuntimeError):
    pass


def image_part(path: Path) -> dict:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data}"}}


async def chat_json(model: str, messages: list[dict], max_tokens: int = 1500, timeout: float = 60.0) -> dict:
    """Ask for a JSON object. Fails if the API answers with a different model than the one requested:
    Vultr silently falls back to another model for an unknown id (D17)."""
    key = os.environ.get("VULTR_INFERENCE_API_KEY", "")
    if not key:
        raise InferenceError("inference key is not configured")
    body = {"model": model, "messages": messages, "max_tokens": max(max_tokens, MIN_TOKENS), "temperature": 0}
    started = time.monotonic()
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{BASE_URL}/chat/completions", json=body,
                                 headers={"Authorization": f"Bearer {key}"})
    if resp.status_code != 200:
        raise InferenceError(f"inference returned HTTP {resp.status_code}")
    payload = resp.json()
    if payload.get("model") != model:
        raise InferenceError(f"asked for {model}, got {payload.get('model')}")
    content = (payload["choices"][0]["message"].get("content") or "").strip()
    return {
        "model": model,
        "seconds": round(time.monotonic() - started, 2),
        "usage": payload.get("usage", {}),
        "data": parse_json_object(content),
    }


def parse_json_object(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise InferenceError("model did not return a JSON object")
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise InferenceError(f"model returned invalid JSON: {exc}") from exc
