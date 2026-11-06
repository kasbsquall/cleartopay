import asyncio

import pytest

from app import inference
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
