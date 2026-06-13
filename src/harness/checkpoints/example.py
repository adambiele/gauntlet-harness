"""Example checkpoint lane — run concrete call, compare to expected (design.md §4).

For each ``ExampleCase`` in the claim, calls ``run_call(module_source, target, args,
kwargs)`` inside the subprocess sandbox and checks whether the result equals
``case.expected``.  First failure short-circuits; all cases must pass for PASS.

Evidence on failure names whether the problem was an exception/error or a value
mismatch (``expected X, got Y``).
"""

from __future__ import annotations

import datetime
import time

from harness.checkpoints.sandbox import run_call
from harness.contracts import CheckpointResult, ExampleClaim, SymbolInfo, Verdict

__all__ = ["check_example"]

LANE = "example"


def check_example(
    claim: ExampleClaim,
    symbol: SymbolInfo,
    module_source: str,
) -> CheckpointResult:
    """Run the example lane: call the symbol for each case, compare to expected.

    Returns a ``CheckpointResult``:
    * ``PASS`` — every case returned the expected value.
    * ``FAIL`` — first failing case's evidence (value mismatch or sandbox error).
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

    if not claim.cases:
        return _result(Verdict.FAIL, "no cases provided")

    for i, case in enumerate(claim.cases):
        result = run_call(module_source, claim.target, case.args, case.kwargs)

        if not result.ok:
            # Sandbox error: exception, timeout, symbol missing, etc.
            if result.timed_out:
                evidence = f"case {i}: execution timed out"
            else:
                evidence = f"case {i}: {result.error or 'sandbox error (no detail)'}"
            return _result(Verdict.FAIL, evidence)

        if result.value != case.expected:
            evidence = (
                f"case {i}: expected {case.expected!r}, got {result.value!r}"
            )
            return _result(Verdict.FAIL, evidence)

    return _result(Verdict.PASS, f"all {len(claim.cases)} case(s) passed")
