"""Checkpoint runner — routes a claim to its lane and wraps in an OTel span.

``verify`` is the single entry point the harness loop calls.  It dispatches on
``claim.type``:
* ``"signature"`` → ``signature.check_signature``
* ``"example"``   → ``example.check_example``
* ``"behavioral"``→ ``behavioral.check_behavioral``
* ``"description"``→ ``INCONCLUSIVE`` (no mechanical check; routes to triage)

Each lane call is wrapped in::

    with span(f"{SPAN_VERIFY}.{lane}", **{ATTR_LANE: lane, ATTR_VERDICT: verdict}):

so the full span tree is ``run → symbol → verify.<lane>`` as required by design.md §10.
The verdict attribute is stamped *after* the lane returns (post-processing on the span
object — OTel attributes can be set any time before the span closes).
"""

from __future__ import annotations

import datetime

from harness.checkpoints.behavioral import LANE as LANE_BEHAVIORAL
from harness.checkpoints.behavioral import check_behavioral
from harness.checkpoints.example import LANE as LANE_EXAMPLE
from harness.checkpoints.example import check_example
from harness.checkpoints.signature import LANE as LANE_SIGNATURE
from harness.checkpoints.signature import check_signature
from harness.contracts import (
    BehavioralClaim,
    CheckpointResult,
    Claim,
    DescriptionClaim,
    ExampleClaim,
    SignatureClaim,
    SymbolInfo,
    Verdict,
)
from harness.observability import ATTR_LANE, ATTR_VERDICT, SPAN_VERIFY, span

__all__ = ["verify"]

LANE_DESCRIPTION = "description"


def verify(
    claim: Claim,
    symbol: SymbolInfo,
    module_source: str,
) -> CheckpointResult:
    """Route ``claim`` to the appropriate checkpoint lane and return a ``CheckpointResult``.

    The OTel span is opened *before* the lane call so the lane's wall-clock time is
    captured inside the span.  The verdict attribute is set on the span after the lane
    returns.

    ``DescriptionClaim`` → ``INCONCLUSIVE`` with no lane execution (design.md §6 step 4:
    INCONCLUSIVE claims are escalated to triage, never retried).
    """
    if isinstance(claim, DescriptionClaim):
        # No mechanical check available; route to human triage.
        lane = LANE_DESCRIPTION
        with span(f"{SPAN_VERIFY}.{lane}", **{ATTR_LANE: lane}) as otel_span:
            result = _make_inconclusive(claim, symbol, lane)
            otel_span.set_attribute(ATTR_VERDICT, result.verdict.value)
        return result

    if isinstance(claim, SignatureClaim):
        lane = LANE_SIGNATURE
        with span(f"{SPAN_VERIFY}.{lane}", **{ATTR_LANE: lane}) as otel_span:
            result = check_signature(claim, symbol, module_source)
            otel_span.set_attribute(ATTR_VERDICT, result.verdict.value)
        return result

    if isinstance(claim, ExampleClaim):
        lane = LANE_EXAMPLE
        with span(f"{SPAN_VERIFY}.{lane}", **{ATTR_LANE: lane}) as otel_span:
            result = check_example(claim, symbol, module_source)
            otel_span.set_attribute(ATTR_VERDICT, result.verdict.value)
        return result

    if isinstance(claim, BehavioralClaim):
        lane = LANE_BEHAVIORAL
        with span(f"{SPAN_VERIFY}.{lane}", **{ATTR_LANE: lane}) as otel_span:
            result = check_behavioral(claim, symbol, module_source)
            otel_span.set_attribute(ATTR_VERDICT, result.verdict.value)
        return result

    # Unreachable for valid discriminated union, but defensive fallback.
    lane = "unknown"
    with span(f"{SPAN_VERIFY}.{lane}", **{ATTR_LANE: lane}) as otel_span:
        result = _make_inconclusive(claim, symbol, lane)
        otel_span.set_attribute(ATTR_VERDICT, result.verdict.value)
    return result


def _make_inconclusive(claim: Claim, symbol: SymbolInfo, lane: str) -> CheckpointResult:
    """Build an INCONCLUSIVE result (no execution — description or unknown type)."""
    return CheckpointResult(
        symbol=symbol.name,
        claim=claim,
        verdict=Verdict.INCONCLUSIVE,
        evidence="no mechanical check available for this claim type",
        code_hash=symbol.code_hash,
        lane=lane,
        timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        duration_ms=0.0,
    )
