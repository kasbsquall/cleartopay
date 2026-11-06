"""Vendor name normalization. Exact means equal after normalization; anything looser goes to a human."""
import re
import unicodedata

LEGAL_SUFFIXES = {
    "inc", "incorporated", "llc", "l l c", "ltd", "limited", "corp", "corporation",
    "co", "company", "lp", "llp", "pllc", "pc", "plc",
}


def normalize(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).replace("\xa0", " ").lower()
    text = "".join(ch for ch in text if not unicodedata.combining(ch))  # José -> jose
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


STOPWORDS = {"the", "of", "de", "and"}
ABBREVIATIONS = {
    "intl": "international", "int": "international", "natl": "national", "corp": "corporation",
    "mfg": "manufacturing", "grp": "group", "govt": "government", "assn": "association",
    "bros": "brothers", "svcs": "services", "svc": "service", "dept": "department", "co": "company",
}


def _tokens(name: str) -> list[str]:
    return [ABBREVIATIONS.get(w, w) for w in normalize(name).split() if w not in STOPWORDS]


def _stem(word: str) -> str:
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("s") and len(word) > 3:
        return word[:-1]
    return word


def _edits(a: str, b: str) -> int:
    """Edit distance that counts swapping two neighbouring letters as one edit."""
    d = [[i + j if i * j == 0 else 0 for j in range(len(b) + 1)] for i in range(len(a) + 1)]
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] != b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[-1][-1]


def _skeleton(word: str) -> str:
    """First letter plus the consonants, doubles collapsed: Mohamed, Muhammad and Mohammed give mhmd."""
    out = word[0]
    for ch in word[1:]:
        if ch not in "aeiouy" and ch != out[-1]:
            out += ch
    return out


def _close(a: str, b: str) -> bool:
    """Same word, plural, prefix (Air, Airlines), or a spelling variant: one edit in 5+ letters, two in
    7+, or the same consonants in 5+ letters (transliterations)."""
    if a == b or _stem(a) == _stem(b):
        return True
    short, long_ = sorted((a, b), key=len)
    if len(short) >= 3 and long_.startswith(short):
        return True
    if len(short) < 5:
        return False
    return _edits(a, b) <= (2 if len(short) >= 7 else 1) or _skeleton(a) == _skeleton(b)


def _covered(small: list[str], big: list[str]) -> bool:
    return all(any(_close(x, y) for y in big) for x in small)


def same_name(candidate: str, vendor_name: str) -> bool:
    """Could this listed name be the vendor? Used to decide which near matches a person must see.

    True when every word of each name has a close word in the other, when one name contains every
    word of the other, allowing spelling variants (a dropped or added word), or when the names are the
    same with the spaces removed. A list entry that shares no close word with the vendor is another entity.
    """
    a, b = _tokens(candidate), _tokens(vendor_name)
    if not a or not b:
        return False
    if set(a) <= set(b) or set(b) <= set(a):
        return True
    if _covered(a, b) and _covered(b, a):
        return True
    # One name inside the other with spelling variants ("Hamaz" in ISLAMIC RESISTANCE MOVEMENT HAMAS).
    # This also sends "Crocs" to a person for CROCUS NANOELECTRONICS: the price of catching Hamaz.
    short, long_ = sorted((a, b), key=len)
    if _covered(short, long_):
        return True
    ja, jb = "".join(a), "".join(b)
    return ja == jb or _close(ja, jb)
