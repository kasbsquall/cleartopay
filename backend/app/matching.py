"""Vendor name normalization. Exact means equal after normalization; anything looser goes to a human."""
import re
import unicodedata

LEGAL_SUFFIXES = {
    "inc", "incorporated", "llc", "l l c", "ltd", "limited", "corp", "corporation",
    "co", "company", "lp", "llp", "pllc", "pc", "plc",
}


def normalize(name: str) -> str:
    text = unicodedata.normalize("NFKC", name).replace("\xa0", " ").lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    words = text.split()
    while words and words[-1] in LEGAL_SUFFIXES:
        words.pop()
    return " ".join(words)


def is_exact(candidate: str, vendor_name: str) -> bool:
    return normalize(candidate) == normalize(vendor_name) != ""


def mentions(candidate: str, vendor_name: str) -> bool:
    """True when the vendor's normalized name appears inside the candidate name."""
    core = normalize(vendor_name)
    return bool(core) and core in normalize(candidate)
