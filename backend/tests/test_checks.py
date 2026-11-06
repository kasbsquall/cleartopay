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


# --- near matches: only a name that could be the vendor goes to a human (2026-11-06) -------------
from app.matching import same_name  # noqa: E402
from app.models import Record  # noqa: E402

def ofac_reading(*rows: tuple[str, str], listed: str = "SDN") -> Reading:
    return Reading(result_count=len(rows), records=tuple(
        Record(name=n, detail={"score": s, "list": listed, "programs": "X"}) for n, s in rows))


@pytest.mark.parametrize("candidate, vendor", [
    ("BANCO NACIONAL DE CUBA", "Banco Nacional Cuba"),          # a word dropped
    ("QODS AVIATION INDUSTRIES", "Qods Aviation Industry"),     # plural
    ("BANK MARKAZI JOMHOURI ISLAMI IRAN", "Bank Markazi"),      # vendor typed the short name
    ("BANK SADERAT PLC", "Bank Saderat PLC London Branch"),     # vendor typed a longer name
    ("AEROCARIBBEAN AIRLINES", "Aero Caribbean Airlines"),      # spacing
    ("DAVINA", "DaVita Inc."),                                  # one letter apart
    ("ROSNEFT TRADING S.A.", "Rosneft Trading"),
    ("BANK SADERAT IRAN", "Bank Sadreat Iran"),                 # two letters swapped
    ("BANK SADERAT IRAN", "Bank Saderet"),                      # a word dropped and a typo
    ("JOSE PEREZ", "José Pérez"),                               # accents
    ("BANK MELLI IRAN INTERNATIONAL", "Bank Melli Iran Intl"),  # abbreviation
    ("MUHAMMAD AL-ZAWAHIRI", "Mohammed Al-Zawahiri"),           # transliteration, two letters
    ("HEZBOLLAH", "Hezbolah"),
    ("ANSAR HEZBOLLAH", "Hezbolah"),                            # real OFAC rows for this query, score 98
    ("EXTERNAL SECURITY ORGANIZATION OF HEZBOLLAH", "Hezbolah"),
    ("HUAWEI TECHNOLOGIES CO., LTD.", "Huawai"),                # found by the second review
    ("WAGNER GROUP", "Wagnar"),
    ("ISLAMIC RESISTANCE MOVEMENT HAMAS", "Hamaz"),
    ("MAHAN AIR", "Mahan Airlines"),                            # prefix
    ("MUHAMMAD ALI", "Mohamed Ali"),                            # transliteration, three letters
    ("CROCUS NANOELECTRONICS", "Crocs, Inc."),                  # accepted false alarms, see matching.py
    ("CROSS OCEAN", "Crocs, Inc."),
    ("BALLER HOLDINGS", "Ball Corporation"),
])
def test_names_that_could_be_the_vendor(candidate, vendor):
    assert same_name(candidate, vendor)


@pytest.mark.parametrize("candidate, vendor", [
    ("ABS CORPORATION", "Ball Corporation"),
    ("B K SALES CORPORATION", "Ball Corporation"),
    ("CAMPBELL, David", "DaVita Inc."),
    ("Inc.", "LLC"),
])
def test_names_that_cannot_be_the_vendor(candidate, vendor):
    assert not same_name(candidate, vendor)


def test_ofac_near_names_of_other_entities_are_clear_and_kept_in_the_file():
    reading = ofac_reading(("ABS CORPORATION", "91"), ("B K SALES CORPORATION", "91"))
    outcome = ofac.judge(reading, Vendor("Ball Corporation"))
    assert outcome.verdict is Verdict.CLEAR
    assert "none could be this vendor" in outcome.reason
    assert outcome.reading.records == reading.records


def test_ofac_one_plausible_name_among_many_goes_to_a_human():
    reading = ofac_reading(("CAMPBELL, David", "90"), ("DAVINA", "90"))
    outcome = ofac.judge(reading, Vendor("DaVita Inc."))
    assert outcome.verdict is Verdict.REVIEW
    assert "DAVINA" in outcome.reason


@pytest.mark.parametrize("shown, vendor", [("HEZBOLLAH", "Hezbolah"), ("CENTRAL BANK OF IRAN", "Central Bank of Irn")])
def test_ofac_alias_shown_by_the_search_goes_to_a_human(shown, vendor):
    assert ofac.judge(ofac_reading((shown, "95")), Vendor(vendor)).verdict is Verdict.REVIEW


@pytest.mark.parametrize("score", ["100", "100.0", "", "n/a"])
def test_ofac_exact_or_unreadable_score_goes_to_a_human_whatever_the_name(score):
    reading = ofac_reading(("ABS CORPORATION", score))
    assert ofac.judge(reading, Vendor("Ball Corporation")).verdict is Verdict.REVIEW


def test_ofac_rows_from_other_lists_go_to_a_human():
    reading = ofac_reading(("ABS CORPORATION", "91"), listed="Non-SDN")
    assert ofac.judge(reading, Vendor("Ball Corporation")).verdict is Verdict.REVIEW


def test_ofac_rows_we_could_not_read_go_to_a_human():
    reading = Reading(result_count=5, records=ofac_reading(("ABS CORPORATION", "91")).records)
    assert ofac.judge(reading, Vendor("Ball Corporation")).verdict is Verdict.REVIEW


def test_sam_any_result_that_is_not_an_active_exact_exclusion_goes_to_a_human():
    recs = (Record(name="Coors Plumbing LLC", detail={"status": "Active", "uei": "X"}),)
    assert sam.judge(Reading(result_count=1, records=recs), Vendor("Molson Coors Beverage Company")).verdict is Verdict.REVIEW


def test_ofac_real_rows_for_a_misspelled_sanctioned_name_go_to_a_human():
    # The 6 Nov 2026 OFAC search for "Hezbolah" listed 11 rows like these, none of them HEZBOLLAH alone.
    reading = ofac_reading(("ANSAR HEZBOLLAH", "98"), ("KATA'IB HEZBOLLAH", "98"), ("CENTRAL BANK OF VENEZUELA", "92"))
    assert ofac.judge(reading, Vendor("Hezbolah")).verdict is Verdict.REVIEW
