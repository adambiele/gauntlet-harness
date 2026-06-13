"""Behavioral checkpoint lane — run assert snippets in the sandbox (design.md §4).

For each snippet in ``BehavioralClaim.asserts``, calls
``run_assert(module_source, claim.target, snippet)``.  A passing assert gives ``ok=True``;
any exception or ``AssertionError`` gives ``ok=False`` with the real traceback.

S0 note (from A2 spec):
    ``run_assert`` passes **no** args to the symbol — ``result`` in the snippet namespace
    is a best-effort ``symbol()`` call (returns ``None`` for multi-arg functions).
    Behavioral snippets are therefore expected to be **self-contained**: they call the
    symbol by name with explicit inputs (e.g. ``assert sort_items([3,1,2]) == [1,2,3]``).
    Do NOT write snippets that rely on a pre-populated ``result`` for functions that
    require arguments.

All snippets must pass for PASS; first failure short-circuits and its real traceback
becomes the evidence.
"""

from __future__ import annotations

import datetime
import time

from harness.checkpoints.sandbox import run_assert
from harness.contracts import BehavioralClaim, CheckpointResult, SymbolInfo, Verdict

__all__ = ["check_behavioral"]

LANE = "behavioral"


def check_behavioral(
    claim: BehavioralClaim,
    symbol: SymbolInfo,
    module_source: str,
) -> CheckpointResult:
    """Run the behavioral lane: exec each assert snippet in the sandbox.

    Returns a ``CheckpointResult``:
    * ``PASS`` — all snippets ran without exception.
    * ``FAIL`` — first failing snippet's evidence (real traceback or timeout message).
    """
    start = time.monotonic()
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")

    def _result(verdict: Verdict, evidence: str) -> CheckpointResult:
        duration_ms = (time.monotonic() - start) * 1000
        return CheckpointResult(
            symbol=symbol.name,
            claim=claim,
            verdict=verdict,
            evidence=evidence,
            code_hash=symbol.code_hash,
            lane=LANE,
            timestamp=timestamp,
            duration_ms=duration_ms,
        )

    if not claim.asserts:
        return _result(Verdict.FAIL, "no assert snippets provided")

    for i, snippet in enumerate(claim.asserts):
        result = run_assert(module_source, claim.target, snippet)

        if not result.ok:
            if result.timed_out:
                evidence = f"snippet {i}: execution timed out"
            else:
                evidence = result.error or f"snippet {i}: sandbox error (no detail)"
            return _result(Verdict.FAIL, evidence)

    return _result(Verdict.PASS, f"all {len(claim.asserts)} snippet(s) passed")
