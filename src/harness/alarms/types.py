"""Alarm contracts — structured, named, severity + recommended action (design.md §7).

This module is types only. Emit logic (raise + append to ``alarms.jsonl``) is Session A4
(``alarms/emit.py``) — deliberately not built here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

__all__ = [
    "Severity",
    "AlarmType",
    "REGISTRY",
    "Alarm",
    "PHANTOM_API",
    "SIGNATURE_MISMATCH",
    "EXAMPLE_FAILED",
    "BEHAVIOR_CONTRADICTION",
    "MALFORMED_CLAIM",
    "UNVERIFIABLE_CLAIM",
    "SECRET_LEAK",
]


class Severity(str, Enum):
    """Alarm severity. BLOCK = drop/redact immediately; others route to retry/triage."""

    BLOCK = "block"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class AlarmType:
    """A registered alarm kind: a name, its severity, and the recommended action."""

    name: str
    severity: Severity
    recommended_action: str


# The frozen registry. Each constant is also exported by name for direct reference.
PHANTOM_API = AlarmType("PHANTOM_API", Severity.BLOCK, "drop claim — symbol does not exist")
SIGNATURE_MISMATCH = AlarmType("SIGNATURE_MISMATCH", Severity.HIGH, "regenerate with the real signature")
EXAMPLE_FAILED = AlarmType("EXAMPLE_FAILED", Severity.HIGH, "regenerate; feed actual traceback")
BEHAVIOR_CONTRADICTION = AlarmType("BEHAVIOR_CONTRADICTION", Severity.BLOCK, "regenerate; feed the counterexample")
MALFORMED_CLAIM = AlarmType("MALFORMED_CLAIM", Severity.HIGH, "regenerate; feed schema error")
UNVERIFIABLE_CLAIM = AlarmType("UNVERIFIABLE_CLAIM", Severity.LOW, "escalate to human")
SECRET_LEAK = AlarmType("SECRET_LEAK", Severity.BLOCK, "redact and regenerate")

REGISTRY: dict[str, AlarmType] = {
    t.name: t
    for t in (
        PHANTOM_API,
        SIGNATURE_MISMATCH,
        EXAMPLE_FAILED,
        BEHAVIOR_CONTRADICTION,
        MALFORMED_CLAIM,
        UNVERIFIABLE_CLAIM,
        SECRET_LEAK,
    )
}


@dataclass
class Alarm:
    """A raised alarm instance — what gets appended to ``alarms.jsonl`` and streamed.

    ``type`` is the registry name (e.g. ``"PHANTOM_API"``); ``severity`` and
    ``recommended_action`` are copied from the registry entry at emit time so each record
    is self-describing. ``claim_ref`` optionally points at the offending claim.
    """

    type: str
    severity: Severity
    symbol: str
    claim_ref: Optional[str]
    message: str
    recommended_action: str
    timestamp: str
