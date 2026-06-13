"""Shared data contracts — the keystone seams every other session imports.

FROZEN. Public names and field shapes here are the contract. Downstream sessions
(material, checkpoints, guardrails, worker, persistence, http, dashboard) depend on
these not changing. See docs/planning/design.md §3.

Two modelling styles coexist on purpose:

* **Claims** are pydantic models (a discriminated union on ``type``). They cross the
  trust boundary — a (possibly weak) model emits them as JSON, so they must be
  *validated*. ``parse_claims`` is the single validation gate; malformed input there is
  how the loop catches ``MALFORMED_CLAIM`` (design.md §6).
* **Engine records** (``SymbolInfo``, ``CodeContext``, ``CheckpointResult``) are plain
  dataclasses. They are constructed by our own deterministic code, never by the model,
  so they need no validation — just a stable shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Annotated, Any, Callable, Literal, Optional, Union

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

__all__ = [
    "Verdict",
    "SignatureClaim",
    "ExampleCase",
    "ExampleClaim",
    "BehavioralClaim",
    "DescriptionClaim",
    "Claim",
    "parse_claims",
    "ClaimParseError",
    "SymbolInfo",
    "CodeContext",
    "CheckpointResult",
]


class Verdict(str, Enum):
    """Outcome of a checkpoint lane.

    ``PASS`` means "not falsified for the inputs tested" — verified-but-low-confidence,
    never rendered as a proof-for-all-inputs. ``FAIL`` is decisive and blocking.
    ``INCONCLUSIVE`` routes to human triage (no retry). See design.md §4.
    """

    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"


# --------------------------------------------------------------------------------------
# The claim union — one shape per type, tagged by ``type``, pydantic-validated.
# A claim only ever carries fields relevant to its type. Multi-check still works *within*
# a type (an ExampleClaim holds several cases; a BehavioralClaim several asserts).
# --------------------------------------------------------------------------------------


class SignatureClaim(BaseModel):
    """A claim about a symbol's signature — verified by AST diff, no execution."""

    type: Literal["signature"]
    target: str
    prose: str
    claimed_signature: str  # e.g. "(x: int, y: int = 0) -> int"


class ExampleCase(BaseModel):
    """One concrete call: ``target(*args, **kwargs)`` is expected to equal ``expected``."""

    args: list = Field(default_factory=list)
    kwargs: dict = Field(default_factory=dict)
    expected: Any = None


class ExampleClaim(BaseModel):
    """A claim backed by concrete input/output cases — the harness builds each call."""

    type: Literal["example"]
    target: str
    prose: str
    cases: list[ExampleCase]


class BehavioralClaim(BaseModel):
    """A claim backed by assert snippets run in the sandbox.

    Each snippet runs in a namespace holding the symbol (by name) plus ``result``,
    ``args`` and ``kwargs``. An ``AssertionError`` (or any exception) → FAIL.
    """

    type: Literal["behavioral"]
    target: str
    prose: str
    asserts: list[str]


class DescriptionClaim(BaseModel):
    """Free prose that is not mechanically checkable.

    Rendered "unverified" — never proven, never a FAIL on its own.
    """

    type: Literal["description"]
    target: str
    prose: str


Claim = Annotated[
    Union[SignatureClaim, ExampleClaim, BehavioralClaim, DescriptionClaim],
    Field(discriminator="type"),
]

# A reusable adapter for the union — validates a JSON list of claims in one pass.
_CLAIM_LIST_ADAPTER: TypeAdapter[list[Claim]] = TypeAdapter(list[Claim])


class ClaimParseError(ValueError):
    """Raised by ``parse_claims`` when input is not a valid list of claims.

    Wraps the underlying pydantic ``ValidationError`` (or JSON error). The loop turns
    this into a ``MALFORMED_CLAIM`` alarm and feeds ``.schema_error`` back to the worker.
    """

    def __init__(self, message: str, *, schema_error: Optional[Exception] = None) -> None:
        super().__init__(message)
        self.schema_error = schema_error


def parse_claims(data: Any) -> list[Claim]:
    """Parse a JSON list (or already-decoded list) into validated ``Claim`` objects.

    Accepts either a JSON string or an already-decoded Python list. Any malformed input
    — bad JSON, not a list, unknown ``type``, missing/extra fields — raises
    ``ClaimParseError``. This is the single validation gate referenced by design.md §3:
    it is *how* a weak model's mistakes get caught (→ ``MALFORMED_CLAIM``).
    """
    try:
        if isinstance(data, (str, bytes, bytearray)):
            claims = _CLAIM_LIST_ADAPTER.validate_json(data)
        else:
            claims = _CLAIM_LIST_ADAPTER.validate_python(data)
    except ValidationError as exc:
        raise ClaimParseError(f"claim list failed schema validation: {exc}", schema_error=exc) from exc
    except ValueError as exc:  # e.g. invalid JSON text
        raise ClaimParseError(f"could not decode claims JSON: {exc}", schema_error=exc) from exc
    return claims


# --------------------------------------------------------------------------------------
# Engine records — plain dataclasses, constructed by our own deterministic code.
# --------------------------------------------------------------------------------------


@dataclass
class SymbolInfo:
    """A single symbol extracted from the target module — by AST, never imported.

    Carries **source text, not a live callable** (design.md §4b): the read path must not
    import the target. ``callable`` is an optional convenience for callers that already
    hold a live object (e.g. the harness documenting itself); the verification lanes do
    not rely on it — they re-exec ``source`` / ``module_source`` inside the sandbox.
    """

    name: str
    signature: str
    source: str
    docstring: Optional[str]
    lineno: int
    code_hash: str
    callable: Optional[Callable] = None


@dataclass
class CodeContext:
    """The full extracted view of a target module.

    ``module_source`` is the complete source text the execution lanes hand to the
    sandbox (which re-execs it to define the symbol). ``symbols`` maps name → info.
    """

    module_path: str
    symbols: dict[str, SymbolInfo]
    module_source: str = ""


@dataclass
class CheckpointResult:
    """The receipt for one claim run through one lane.

    ``evidence`` is the human-readable proof: a signature diff, a traceback, or a
    counterexample. ``code_hash`` ties the result to the exact symbol source that
    produced it, which is also the replay cache key (design.md §8).
    """

    symbol: str
    claim: Claim
    verdict: Verdict
    evidence: str
    code_hash: str
    lane: str
    timestamp: str
    duration_ms: float
