import asyncio

import pytest

from app import inference, verifier
from app.models import CheckOutcome, Reading, Verdict
from app.pipeline import reconcile


def outcome(verdict: Verdict, count: int | None = 0) -> CheckOutcome:
    return CheckOutcome(verdict, "parser", Reading(count))


def test_verifier_that_agrees_keeps_the_verdict():
    assert reconcile(outcome(Verdict.CLEAR), {"agrees": True}).verdict == Verdict.CLEAR
    assert reconcile(outcome(Verdict.VERIFIED, 1), {"agrees": True}).verdict == Verdict.VERIFIED


def test_disagreement_or_failure_sends_to_a_human():
    assert reconcile(outcome(Verdict.CLEAR), {"agrees": False, "result_count_seen": 3}).verdict == Verdict.REVIEW
    assert reconcile(outcome(Verdict.VERIFIED, 1), {"agrees": False, "error": "timeout"}).verdict == Verdict.REVIEW


def test_verifier_cannot_clear_a_hit_or_an_error():
    assert reconcile(outcome(Verdict.HIT, 1), {"agrees": True}).verdict == Verdict.HIT
    assert reconcile(outcome(Verdict.ERROR, None), {"agrees": True}).verdict == Verdict.ERROR
    assert reconcile(outcome(Verdict.REVIEW, 2), {"agrees": True}).verdict == Verdict.REVIEW


def test_exact_match_seen_only_by_the_verifier_goes_to_review():
    second = {"agrees": True, "exact_match_seen": True}
    assert reconcile(outcome(Verdict.CLEAR), second).verdict == Verdict.REVIEW


def test_silent_model_fallback_is_rejected(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {"model": "deepseek-v4.1-flash-1017", "choices": [{"message": {"content": "{}"}}]}

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setenv("VULTR_INFERENCE_API_KEY", "test-key")
    monkeypatch.setattr(inference.httpx, "AsyncClient", FakeClient)
    with pytest.raises(inference.InferenceError, match="asked for qwen3.8-27b"):
        asyncio.run(inference.chat_json("qwen3.8-27b", [{"role": "user", "content": "hi"}]))


def test_json_is_extracted_from_fenced_answers():
    assert inference.parse_json_object('```json\n{"result_count": 0}\n```') == {"result_count": 0}


def test_answer_cut_off_by_the_token_budget_is_an_error(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {"model": "glm-5.3", "choices": [{"finish_reason": "length", "message": {"content": None}}]}

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setenv("VULTR_INFERENCE_API_KEY", "test-key")
    monkeypatch.setattr(inference.httpx, "AsyncClient", FakeClient)
    with pytest.raises(inference.InferenceError, match="token budget"):
        asyncio.run(inference.chat_json("glm-5.3", [{"role": "user", "content": "hi"}]))


def test_verifier_reads_without_reasoning(monkeypatch, tmp_path):
    # With reasoning on, qwen3.8-27b spent 3,650 to 7,400 tokens on an empty SAM.gov page and sometimes
    # never answered; with it off it counted 10, 27 and 0 rows right in 6 of 6 runs (eval/results/verifier-budget.json).
    seen = {}

    async def fake_chat_json(model, messages, max_tokens=1500, timeout=60.0, options=None):
        seen.update(options or {})
        return {"model": model, "seconds": 0.5, "data": {"result_count": 0, "exact_match": False}}

    shot = tmp_path / "s.png"
    shot.write_bytes(b"\x89PNG")
    monkeypatch.setattr(verifier, "chat_json", fake_chat_json)
    out = asyncio.run(verifier.verify("sam", "DaVita Inc.", shot, 0))
    assert out["agrees"] is True
    assert seen == {"chat_template_kwargs": {"enable_thinking": False}}
