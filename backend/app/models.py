"""Plain data shapes shared by checks, the sandbox runner and the evidence file."""
from dataclasses import dataclass, field
from enum import Enum


class Verdict(str, Enum):
    CLEAR = "clear"          # source searched, nothing matching the vendor
    HIT = "hit"              # exact name match on a sanctions or exclusion list
    VERIFIED = "verified"    # registry shows the vendor in good standing
    REVIEW = "review"        # something a human has to look at
    ERROR = "error"          # the check could not complete; never treated as clean


@dataclass(frozen=True)
class Vendor:
    legal_name: str
    state: str = ""
    website: str = ""


@dataclass(frozen=True)
class ProbeSpec:
    """Everything the sandbox needs for one check. Built by code, never by the model."""
    check: str
    query: str
    allowed_hosts: tuple[str, ...]
    task: dict
    cpus: int = 1
    memory_mib: int = 2048
    max_seconds: int = 150


@dataclass(frozen=True)
class Record:
    name: str
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Reading:
    """What the page text says, parsed deterministically."""
    result_count: int | None
    records: tuple[Record, ...] = ()
    note: str = ""


@dataclass(frozen=True)
class CheckOutcome:
    verdict: Verdict
    reason: str
    reading: Reading
