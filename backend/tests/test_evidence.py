import hashlib

from app.evidence import manifest_digest, record, sha256_file
from app.models import CheckOutcome, Reading, Record, Verdict
from app.sandbox import ProbeRun


def test_sha256_file_matches_hashlib(tmp_path):
    shot = tmp_path / "s.png"
    shot.write_bytes(b"\x89PNG fake bytes")
    assert sha256_file(shot) == hashlib.sha256(b"\x89PNG fake bytes").hexdigest()


def test_record_keeps_containment_facts_and_hashes(tmp_path):
    shot = tmp_path / "s.png"
    shot.write_bytes(b"img")
    run = ProbeRun(
        sandbox_name="ctp-ofac-abc", ok=True, started_at="2026-11-03T18:40:00+00:00", seconds=8.1,
        destroyed=True, limits={"cpus": 1}, allowed_hosts=("sanctionssearch.ofac.treas.gov",),
        result={"final_url": "https://sanctionssearch.ofac.treas.gov/", "env_names": ["HOME", "PATH"],
                "requests_blocked": [{"url": "https://www.googletagmanager.com/gtag/js", "error": "x"}]},
        screenshot=shot, page_text="Lookup Results: 0 Found",
    )
    outcome = CheckOutcome(Verdict.CLEAR, "0 matches", Reading(0, (Record("X", {"list": "SDN"}),)))
    rec = record("ofac", "Acme", run, outcome)
    assert rec["verdict"] == "clear"
    assert rec["screenshot_sha256"] == hashlib.sha256(b"img").hexdigest()
    assert rec["containment"]["blocked_hosts"] == ["www.googletagmanager.com"]
    assert rec["containment"]["destroyed"] is True
    assert rec["records"] == [{"name": "X", "list": "SDN"}]


def test_decide_blocks_on_any_hit_and_clears_only_when_all_clean():
    from app.pipeline import decide

    assert decide([{"verdict": "clear"}, {"verdict": "hit"}, {"verdict": "error"}]) == "blocked"
    assert decide([{"verdict": "clear"}, {"verdict": "verified"}]) == "clear_to_pay"
    assert decide([{"verdict": "clear"}, {"verdict": "error"}]) == "needs_human"
    assert decide([{"verdict": "clear"}, {"verdict": "review"}]) == "needs_human"
    assert decide([]) == "needs_human"


def test_manifest_digest_changes_when_any_record_changes():
    records = [{"check": "ofac", "verdict": "clear"}]
    tampered = [{"check": "ofac", "verdict": "hit"}]
    assert manifest_digest(records) != manifest_digest(tampered)
    assert manifest_digest(records) == manifest_digest([dict(records[0])])
