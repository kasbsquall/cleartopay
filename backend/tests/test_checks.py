"""Parsers and verdicts against page text captured from real microVM runs on 2026-11-03."""
from pathlib import Path

import pytest

from app.checks import colorado, ofac, sam
from app.matching import is_exact, normalize
from app.models import Reading, Vendor, Verdict

FIXTURES = Path(__file__).parent / "fixtures"


def text(name: str) -> str:
    return (FIXTURES / f"{name}.txt").read_text(encoding="utf-8")


@pytest.mark.parametrize("raw, expected", [
    ("Microsoft Corporation", "microsoft"),
    ("MICROSOFT CORP.", "microsoft"),
    ("Igloo Construction, Inc.", "igloo construction"),
    ("Acme\xa0Holdings LLC", "acme holdings"),
])
def test_normalize_strips_case_punctuation_and_legal_suffixes(raw, expected):
    assert normalize(raw) == expected


def test_exact_match_never_matches_empty_names():
    assert not is_exact("Inc.", "LLC")


def test_ofac_sanctioned_entity_is_a_hit():
    reading = ofac.parse(text("ofac-banco-nacional-de-cuba"))
    assert reading.result_count == 1
    assert reading.records[0].detail["list"] == "SDN"
    outcome = ofac.judge(reading, Vendor("Banco Nacional de Cuba"))
    assert outcome.verdict is Verdict.HIT


def test_ofac_clean_company_is_clear():
    reading = ofac.parse(text("ofac-microsoft-corporation"))
    assert reading.result_count == 0
    assert ofac.judge(reading, Vendor("Microsoft Corporation")).verdict is Verdict.CLEAR


def test_sam_active_exclusion_is_a_hit():
    reading = sam.parse(text("sam-igloo-construction-inc"))
    assert reading.result_count == 2
    assert reading.records[0].detail == {"status": "Active", "uei": "EHYLYBB5CUX9"}
    assert sam.judge(reading, Vendor("Igloo Construction, Inc.")).verdict is Verdict.HIT


def test_sam_no_matches_is_clear():
    reading = sam.parse(text("sam-microsoft-corporation"))
    assert reading.result_count == 0
    assert sam.judge(reading, Vendor("Microsoft Corporation")).verdict is Verdict.CLEAR


def test_colorado_good_standing_is_verified_and_lookalike_is_parsed():
    reading = colorado.parse(text("co-microsoft-corporation"))
    assert reading.result_count == 2
    names = [r.name for r in reading.records]
    assert "MICROSOFT CORPORATION" in names
    assert any("TRUSTITALIA" in n for n in names)
    ms = next(r for r in reading.records if r.name == "MICROSOFT CORPORATION")
    assert ms.detail["status"] == "Good Standing"
    assert ms.detail["id_number"] == "19931121425"
    assert colorado.judge(reading, Vendor("Microsoft Corporation")).verdict is Verdict.VERIFIED


def test_colorado_unknown_vendor_needs_a_human():
    reading = colorado.parse(text("co-zzqx-imaginary-vendor-llc"))
    assert reading.result_count == 0
    assert colorado.judge(reading, Vendor("Zzqx Imaginary Vendor LLC")).verdict is Verdict.REVIEW


@pytest.mark.parametrize("module", [ofac, sam, colorado])
def test_unreadable_page_fails_closed(module):
    reading = module.parse("Access denied")
    assert reading.result_count is None
    assert module.judge(reading, Vendor("Anyone")).verdict is Verdict.ERROR


@pytest.mark.parametrize("module", [ofac, sam, colorado])
def test_specs_only_allow_their_own_source(module):
    spec = module.build(Vendor("Acme"))
    hosts = " ".join(spec.allowed_hosts)
    assert all(word not in hosts for word in ("vultr", "openai", "googletagmanager"))
    assert spec.task["url"].startswith("https://")
    assert {s["do"] for s in spec.task["steps"]} <= {"fill", "click", "press", "wait_for", "wait_ms"}


def test_reading_without_records_is_not_a_hit():
    outcome = ofac.judge(Reading(result_count=3), Vendor("Acme"))
    assert outcome.verdict is Verdict.REVIEW
