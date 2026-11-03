"""Colorado Secretary of State business database (coloradosos.gov)."""
import re

from ..matching import is_exact, mentions
from ..models import CheckOutcome, ProbeSpec, Reading, Record, Vendor, Verdict

NAME = "colorado"
HOSTS = ("www.coloradosos.gov",)
URL = "https://www.coloradosos.gov/biz/BusinessEntityCriteriaExt.do"
COLUMNS = ("index", "id_number", "document_number", "name", "event", "status", "form", "formation_date")
ROW_START = re.compile(r"^\d+\t")


def build(vendor: Vendor) -> ProbeSpec:
    steps = [
        {"do": "fill", "selector": "#searchCriteria", "value": vendor.legal_name},
        {"do": "click", "selector": "input[type=submit][value=Search]"},
        {"do": "wait_ms", "ms": 2500},
    ]
    return ProbeSpec(check=NAME, query=vendor.legal_name, allowed_hosts=HOSTS,
                     task={"url": URL, "timeout_ms": 40000, "steps": steps})


def _rows(text: str) -> list[str]:
    """Table rows wrap across lines; glue every continuation line back onto its row."""
    rows: list[str] = []
    body = text.split("Formation Date", 1)[-1].split("Terms & conditions", 1)[0]
    for line in body.splitlines():
        if ROW_START.match(line):
            rows.append(line)
        elif rows and line.strip():
            rows[-1] += " " + line
    return rows


def parse(text: str) -> Reading:
    text = text.replace("\xa0", " ")
    if "No results found for the specified name" in text:
        return Reading(result_count=0)
    found = re.search(r"Found\s+(\d+)\s+matching record", text)
    if not found:
        return Reading(result_count=None, note="results header not on page")
    records = []
    for row in _rows(text):
        cells = [" ".join(c.split()) for c in row.split("\t")]
        if len(cells) >= len(COLUMNS):
            detail = dict(zip(COLUMNS, cells))
            records.append(Record(name=detail.pop("name"), detail=detail))
    return Reading(result_count=int(found.group(1)), records=tuple(records))


def judge(reading: Reading, vendor: Vendor) -> CheckOutcome:
    if reading.result_count is None:
        return CheckOutcome(Verdict.ERROR, "Colorado registry page did not show results", reading)
    if reading.result_count == 0:
        return CheckOutcome(Verdict.REVIEW, "no Colorado business registered under this name", reading)
    exact = [r for r in reading.records if is_exact(r.name, vendor.legal_name)]
    if any(r.detail.get("status") == "Good Standing" for r in exact):
        return CheckOutcome(Verdict.VERIFIED, "registered and in good standing", reading)
    if exact:
        return CheckOutcome(Verdict.REVIEW, f"registered, status: {exact[0].detail.get('status')}", reading)
    similar = [r.name for r in reading.records if mentions(r.name, vendor.legal_name)]
    return CheckOutcome(Verdict.REVIEW, "only similar names" + (f": {similar[0]}" if similar else ""), reading)
