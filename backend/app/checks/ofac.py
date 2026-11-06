"""OFAC Sanctions List Search (sanctionssearch.ofac.treas.gov)."""
import re

from ..matching import is_exact, same_name
from ..models import CheckOutcome, ProbeSpec, Reading, Record, Vendor, Verdict

NAME = "ofac"
HOSTS = ("sanctionssearch.ofac.treas.gov",)
URL = "https://sanctionssearch.ofac.treas.gov/"
# OFAC's slider defaults to 100 (exact only). A lower floor surfaces near matches for human review.
MIN_SCORE = 90
COLUMNS = ("name", "address", "type", "programs", "list", "score")


def build(vendor: Vendor) -> ProbeSpec:
    steps = [
        {"do": "fill", "selector": "#ctl00_MainContent_txtLastName", "value": vendor.legal_name},
        {"do": "fill", "selector": "#ctl00_MainContent_Slider1_Boundcontrol", "value": str(MIN_SCORE)},
        {"do": "click", "selector": "#ctl00_MainContent_btnSearch"},
        {"do": "wait_ms", "ms": 2500},
    ]
    return ProbeSpec(check=NAME, query=vendor.legal_name, allowed_hosts=HOSTS,
                     task={"url": URL, "steps": steps})


def parse(text: str) -> Reading:
    found = re.search(r"Lookup Results:\s*(\d+)\s*Found", text)
    if not found:
        return Reading(result_count=None, note="results header not on page")
    records = []
    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line.startswith("Name\tAddress\tType"))
    except StopIteration:
        start = len(lines)
    for line in lines[start + 1:]:
        cells = [c.strip() for c in line.split("\t")]
        if len(cells) < len(COLUMNS):
            break
        records.append(Record(name=cells[0], detail=dict(zip(COLUMNS[1:], cells[1:]))))
    return Reading(result_count=int(found.group(1)), records=tuple(records))


def judge(reading: Reading, vendor: Vendor) -> CheckOutcome:
    if reading.result_count is None:
        return CheckOutcome(Verdict.ERROR, "OFAC page did not show a results count", reading)
    if reading.result_count == 0:
        return CheckOutcome(Verdict.CLEAR, f"0 matches at a minimum score of {MIN_SCORE}", reading)
    if any(is_exact(r.name, vendor.legal_name) for r in reading.records):
        return CheckOutcome(Verdict.HIT, "exact name on an OFAC sanctions list", reading)
    if len(reading.records) < reading.result_count:
        return CheckOutcome(Verdict.REVIEW, f"{reading.result_count} similar names, only {len(reading.records)} readable", reading)
    plausible = [r.name for r in reading.records if _could_be(r, vendor)]
    if plausible:
        return CheckOutcome(Verdict.REVIEW, f"{reading.result_count} similar names, none exact; could be this vendor: {plausible[0]}", reading)
    return CheckOutcome(Verdict.CLEAR, f"{reading.result_count} similar names at score {MIN_SCORE}+; none could be this vendor "
                        f"(closest: {reading.records[0].name})", reading)


def _score(record: Record) -> float:
    try:
        return float(record.detail.get("score", ""))
    except ValueError:
        return 100.0


def _could_be(record: Record, vendor: Vendor) -> bool:
    """OFAC's results table shows the name that matched, alias or not (checked on 6 Nov 2026: a search
    for "Central Bank of Iran" lists CENTRAL BANK OF IRAN, an alias of BANK MARKAZI JOMHOURI ISLAMI IRAN).
    So the shown name is the one to compare. Score 100 and rows from other lists always go to a person."""
    if _score(record) >= 100 or record.detail.get("list", "").strip().upper() != "SDN":
        return True
    return same_name(record.name, vendor.legal_name)
