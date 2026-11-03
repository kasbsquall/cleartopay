"""OFAC Sanctions List Search (sanctionssearch.ofac.treas.gov)."""
import re

from ..matching import is_exact, mentions
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
    close = [r.name for r in reading.records if mentions(r.name, vendor.legal_name)]
    reason = f"{reading.result_count} similar names, none exact" + (f": {close[0]}" if close else "")
    return CheckOutcome(Verdict.REVIEW, reason, reading)
