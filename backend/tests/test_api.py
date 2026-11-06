import time

import pytest
from fastapi.testclient import TestClient

from app import main, store


def fake_record(check: str, verdict: str) -> dict:
    return {"check": check, "verdict": verdict, "containment": {"sandbox": f"ctp-{check}-x", "destroyed": True}}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "RUNS_INDEX_DIR", tmp_path)
    with TestClient(main.app) as test_client:  # one event loop for the whole test, so background runs finish
        yield test_client


def wait_done(client, run_id):
    for _ in range(50):
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] == "done":
            return run
        time.sleep(0.05)
    raise AssertionError("run did not finish")


def test_clean_vendor_can_be_approved(client, monkeypatch):
    async def ok(module, vendor):
        return fake_record(module.NAME, "verified" if module.NAME == "colorado" else "clear")

    monkeypatch.setattr(main, "run_check", ok)
    run_id = client.post("/api/runs", json={"legal_name": "Ball Corporation"}).json()["id"]
    run = wait_done(client, run_id)
    assert run["decision"] == "clear_to_pay"
    assert run["pending"] == []
    approved = client.post(f"/api/runs/{run_id}/approve", json={"approver": "J. Alvarez"}).json()
    assert approved["approval"]["simulated"] is True


def test_hit_blocks_and_approval_is_refused(client, monkeypatch):
    async def hit(module, vendor):
        return fake_record(module.NAME, "hit" if module.NAME == "sam" else "clear")

    monkeypatch.setattr(main, "run_check", hit)
    run_id = client.post("/api/runs", json={"legal_name": "Morales Construction, Inc."}).json()["id"]
    assert wait_done(client, run_id)["decision"] == "blocked"
    assert client.post(f"/api/runs/{run_id}/approve", json={"approver": "J. Alvarez"}).status_code == 409


def test_crash_mid_run_fails_closed(client, monkeypatch):
    async def boom(module, vendor):
        if module.NAME == "sam":
            raise RuntimeError("probe exploded")
        return fake_record(module.NAME, "clear")

    monkeypatch.setattr(main, "run_check", boom)
    run_id = client.post("/api/runs", json={"legal_name": "Acme LLC"}).json()["id"]
    run = wait_done(client, run_id)
    assert run["decision"] == "needs_human"
    assert "sam" in run["pending"]


def test_input_is_validated_and_ids_cannot_escape(client):
    assert client.post("/api/runs", json={"legal_name": "x"}).status_code == 422
    assert client.post("/api/runs", json={"legal_name": "Acme", "state": "colorado"}).status_code == 422
    assert client.get("/api/runs/..%2F..%2Fetc").status_code == 404
