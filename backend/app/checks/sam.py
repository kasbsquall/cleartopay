"""SAM.gov exclusions search (sam.gov/search/?index=ex)."""
import re

from ..matching import is_exact
from ..models import CheckOutcome, ProbeSpec, Reading, Record, Vendor, Verdict

NAME = "sam"
HOSTS = ("sam.gov", "*.sam.gov")
URL = "https://sam.gov/search/?index=ex"
KEYWORD = "input[name=keyword-text]"
STATUS_RE = re.compile(r"^(?P<name>.+?)\s+(?P<status>Active|Inactive)$")


def build(vendor: Vendor) -> ProbeSpec:
    steps = [
        {"do": "wait_for", "selector": KEYWORD},
        {"do": "fill", "selector": KEYWORD, "value": vendor.legal_name},
        {"do": "press", "selector": KEYWORD, "key": "Enter"},
        {"do": "wait_ms", "ms": 5000},
    ]
    return ProbeSpec(check=NAME, query=vendor.legal_name, allowed_hosts=HOSTS,
                     task={"url": URL, "timeout_ms": 45000, "steps": steps})


def parse(text: str) -> Reading:
    if "No matches found" in text:
        return Reading(result_count=0)
    shown = re.search(r"Showing\s+\d+\s*-\s*\d+\s+of\s+(\d+)\s+results", text)
    if not shown:
        return Reading(result_count=None, note="results header not on page")
    lines = [line.strip() for line in text.splitlines()]
    records = []
    for i, line in enumerate(lines[:-2]):
        if lines[i + 1] != "Unique Entity ID":
            continue
        head = STATUS_RE.match(line)
        name, status = (head["name"], head["status"]) if head else (line, "")
        records.append(Record(name=name, detail={"status": status, "uei": lines[i + 2]}))
    return Reading(result_count=int(shown.group(1)), records=tuple(records))


def judge(reading: Reading, vendor: Vendor) -> CheckOutcome:
    if reading.result_count is None:
        return CheckOutcome(Verdict.ERROR, "SAM.gov page did not show a results count", reading)
    if reading.result_count == 0:
        return CheckOutcome(Verdict.CLEAR, "no active exclusions found", reading)
    exact = [r for r in reading.records if is_exact(r.name, vendor.legal_name)]
    if any(r.detail.get("status") == "Active" for r in exact):
        return CheckOutcome(Verdict.HIT, "active exclusion under this exact name", reading)
    return CheckOutcome(Verdict.REVIEW, f"{reading.result_count} exclusion records to compare", reading)
