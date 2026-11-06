"""Build eval/cases.json from sources that are independent of the tool under test.

- OFAC: the official SDN.CSV export (entity rows), downloaded to data/truth/sdn.csv.
- SAM.gov: active exclusions read by hand on sam.gov on 2026-11-03 (listed below with UEI).
- Colorado: the state's open data set "Business Entities in Colorado" (data.colorado.gov 4ykn-tg5h).

Run from the repo root on the VM:  python3 eval/build_cases.py
"""
import csv
import hashlib
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.matching import normalize  # noqa: E402

TRUTH = ROOT / "data" / "truth"
CO_DATASET = "https://data.colorado.gov/resource/4ykn-tg5h.json"
SDN_URL = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.CSV"

SDN_PICKS = [  # entity rows, one per program family, chosen from SDN.CSV on 2026-11-03
    "AEROCARIBBEAN AIRLINES", "BANK MARKAZI JOMHOURI ISLAMI IRAN", "QODS AVIATION INDUSTRIES",
    "OFFICE 39", "ROSNEFT TRADING S.A.", "BANK SADERAT PLC", "FLEURETTE PROPERTIES LIMITED",
    "ALBANIAN NATIONAL ARMY",
]
SAM_PICKS = {  # name as shown on sam.gov -> UEI (active exclusions, classification Firm)
    "RLM Construction Co.": "U5CHAE944Y47", "Morales Construction, Inc.": "K4LRYRWGDMM3",
    "Cantillon Construction Co.": "LC27MFU2W8Q1", "TAB CONSTRUCTION COMPANY, INC.": "EZD7RT2D2MP4",
    "Donora Construction Corp.": "KLU3LDAGYC94", "Newton-Pollack Construction, Inc.": "MFHDANCFMK24",
    "Poff Construction, Inc.": "N2BAU6WNMGV8", "Blaine Construction Company, Inc.": "E7DNZYYHHNT4",
}
CLEAN_PICKS = [  # large companies; Colorado status confirmed in open data below
    "Microsoft Corporation", "Ball Corporation", "DaVita Inc.", "Vail Resorts, Inc.", "Newmont Corporation",
    "Arrow Electronics, Inc.", "Molson Coors Beverage Company", "The Western Union Company", "Crocs, Inc.",
    "Advanced Energy Industries, Inc.", "Ovintiv Inc.", "Frontier Airlines, Inc.",
]
TRICKY = [  # expected: a human looks; auto-clearing any of these is a miss
    {"name": "Banco Nacional Cuba", "why": "SDN entity BANCO NACIONAL DE CUBA with one word dropped"},
    {"name": "Zzqx Imaginary Vendor LLC", "why": "not registered anywhere we check"},
]
# Held out, added 2026-11-06 after the near-match rule changed, so that rule is tested on names it
# was not tuned on. Picked before any run with the new rule.
VARIANTS = [  # SDN entities typed the way a person might; must never be cleared
    {"name": "Qods Aviation Industry", "why": "SDN QODS AVIATION INDUSTRIES, singular"},
    {"name": "Bank Markazi", "why": "SDN BANK MARKAZI JOMHOURI ISLAMI IRAN, short name"},
    {"name": "Aero Caribbean Airlines", "why": "SDN AEROCARIBBEAN AIRLINES, split word"},
    {"name": "Rosneft Trading", "why": "SDN ROSNEFT TRADING S.A., without the legal form"},
    {"name": "Bank Saderat", "why": "SDN BANK SADERAT PLC, without the legal form"},
    {"name": "Hezbolah", "why": "misspelled HEZBOLLAH; found while reviewing the rule, so not held out"},
]
CLEAN_HOLDOUT_CANDIDATES = [  # kept only if Good Standing in Colorado open data and not on the SDN list
    "Liberty Media Corporation", "Chipotle Mexican Grill, Inc.", "Palantir Technologies Inc.", "Woodward, Inc.",
    "Pilgrim's Pride Corporation", "Gates Corporation", "Ibotta, Inc.", "Qurate Retail, Inc.",
]


def sdn_entities() -> set[str]:
    path = TRUTH / "sdn.csv"
    with open(path, encoding="latin-1", newline="") as fh:
        return {normalize(row[1]) for row in csv.reader(fh) if len(row) > 2 and row[2].strip() == "-0-"}


def colorado_status(names: list[str]) -> dict[str, list[str]]:
    inlist = ",".join("'" + n.upper().replace("'", "''") + "'" for n in names)
    query = urllib.parse.urlencode({"$where": f"upper(entityname) in ({inlist})", "$limit": 500})
    with urllib.request.urlopen(f"{CO_DATASET}?{query}", timeout=60) as resp:
        rows = json.load(resp)
    status: dict[str, list[str]] = {}
    for row in rows:
        status.setdefault(normalize(row["entityname"]), []).append(row["entitystatus"])
    return status


def expected_colorado(name: str, co: dict[str, list[str]]) -> str:
    states = co.get(normalize(name), [])
    return "verified" if "Good Standing" in states else "review"


def main() -> None:
    sdn = sdn_entities()
    all_names = (SDN_PICKS + list(SAM_PICKS) + CLEAN_PICKS + [t["name"] for t in TRICKY]
                 + [v["name"] for v in VARIANTS] + CLEAN_HOLDOUT_CANDIDATES)
    co = colorado_status(all_names)
    cases = []
    for name in SDN_PICKS:
        cases.append({"name": name, "group": "ofac_sdn", "expected_decision": ["blocked"],
                      "expected": {"ofac": "hit", "colorado": expected_colorado(name, co)}})
    for name, uei in SAM_PICKS.items():
        cases.append({"name": name, "group": "sam_exclusion", "uei": uei, "expected_decision": ["blocked"],
                      "expected": {"sam": "hit", "ofac_on_sdn": normalize(name) in sdn,
                                   "colorado": expected_colorado(name, co)}})
    for name in CLEAN_PICKS:
        cases.append({"name": name, "group": "clean", "expected_decision": ["clear_to_pay"],
                      "expected": {"ofac_on_sdn": normalize(name) in sdn, "colorado": expected_colorado(name, co)},
                      "assumption": "no SAM.gov exclusion; not independently verified"})
    for item in TRICKY:
        cases.append({"name": item["name"], "group": "tricky", "why": item["why"],
                      "expected_decision": ["needs_human", "blocked"],
                      "expected": {"colorado": expected_colorado(item["name"], co)}})
    for item in VARIANTS:
        cases.append({"name": item["name"], "group": "variant", "why": item["why"],
                      "expected_decision": ["needs_human", "blocked"],
                      "expected": {"colorado": expected_colorado(item["name"], co)}})
    for name in CLEAN_HOLDOUT_CANDIDATES:
        if expected_colorado(name, co) != "verified" or normalize(name) in sdn:
            print(f"holdout skipped: {name}")
            continue
        cases.append({"name": name, "group": "clean_holdout", "expected_decision": ["clear_to_pay"],
                      "expected": {"ofac_on_sdn": False, "colorado": "verified"},
                      "assumption": "no SAM.gov exclusion; not independently verified"})
    sdn_hash = hashlib.sha256((TRUTH / "sdn.csv").read_bytes()).hexdigest()
    out = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": {
            "ofac": {"url": SDN_URL, "sha256": sdn_hash},
            "sam": "sam.gov exclusions search, read by hand 2026-11-03; names and UEIs above",
            "colorado": CO_DATASET,
        },
        "cases": cases,
    }
    (ROOT / "eval" / "cases.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"{len(cases)} cases written")


if __name__ == "__main__":
    main()
