"""Worker contract + a deterministic stub (design.md §5; sessions.md Session 0).

``Worker`` is the swappable seam the loop talks to. The real LLM transports
(``ClaudeWorker``/``LocalWorker``) are Session A5; this module ships only the ABC and a
``StubWorker`` so the loop and every downstream package can be built and tested with
**zero LLM calls**.

``StubWorker`` returns canned, deterministic claims keyed by symbol name. For a symbol
named ``sort_items`` it returns a deliberately WRONG ``ExampleClaim`` so the loop's
FAIL → retry path can be exercised offline (the planted-bug fixture story).
"""

from __future__ import annotations

import ast
import doctest
from abc import ABC, abstractmethod
from typing import Any, Optional

from harness.alarms.types import Alarm
from harness.contracts import (
    BehavioralClaim,
    Claim,
    DescriptionClaim,
    ExampleCase,
    ExampleClaim,
    SignatureClaim,
    SymbolInfo,
)

__all__ = ["Worker", "StubWorker", "SeededWorker"]


class Worker(ABC):
    """The worker seam: turn a symbol (+ prior alarms) into a set of claims.

    The loop never knows which concrete worker ran (the model-swap Bonus). ``feedback``
    carries the alarms from the previous attempt so a real worker can regenerate only the
    failed claims with their evidence (design.md §6).
    """

    @abstractmethod
    def generate(
        self, symbol: SymbolInfo, feedback: Optional[list[Alarm]] = None
    ) -> list[Claim]:
        """Return a list of claims about ``symbol``, optionally informed by ``feedback``."""


class StubWorker(Worker):
    """Deterministic, LLM-free worker for building/testing the loop offline.

    Claims are canned per symbol name. ``sort_items`` intentionally gets a wrong
    ExampleClaim (claims ``sort_items([3,1,2]) == [1,2,3]`` — a real ``sort_items`` that
    reverses would FAIL it) so the FAIL/retry/escalate path is exercisable with no model.
    """

    def generate(
        self, symbol: SymbolInfo, feedback: Optional[list[Alarm]] = None
    ) -> list[Claim]:
        name = symbol.name

        if name == "sort_items":
            # Planted-bug fixture: this claim is a LIE about a reversing sort_items.
            return [
                SignatureClaim(
                    type="signature",
                    target=name,
                    prose="sort_items takes a list and returns a list.",
                    claimed_signature=symbol.signature,
                ),
                ExampleClaim(
                    type="example",
                    target=name,
                    prose="Sorting [3, 1, 2] yields [1, 2, 3].",
                    cases=[ExampleCase(args=[[3, 1, 2]], kwargs={}, expected=[1, 2, 3])],
                ),
            ]

        if name == "add":
            return [
                SignatureClaim(
                    type="signature",
                    target=name,
                    prose="add takes two numbers and returns their sum.",
                    claimed_signature=symbol.signature,
                ),
                ExampleClaim(
                    type="example",
                    target=name,
                    prose="add(2, 3) returns 5.",
                    cases=[
                        ExampleCase(args=[2, 3], kwargs={}, expected=5),
                        ExampleCase(args=[0, 0], kwargs={}, expected=0),
                    ],
                ),
                BehavioralClaim(
                    type="behavioral",
                    target=name,
                    prose="add is commutative.",
                    asserts=[f"assert {name}(1, 2) == {name}(2, 1)"],
                ),
            ]

        # Generic fallback: an unverifiable description plus a signature echo. Enough for
        # the loop to have something to gate/verify for any symbol.
        return [
            SignatureClaim(
                type="signature",
                target=name,
                prose=f"{name} has the signature {symbol.signature}.",
                claimed_signature=symbol.signature,
            ),
            DescriptionClaim(
                type="description",
                target=name,
                prose=symbol.docstring or f"{name} is a function in the target module.",
            ),
        ]


# ---------------------------------------------------------------------------
# SeededWorker — deterministic lie on attempt 1, real model corrects on retry
# ---------------------------------------------------------------------------

def _corrupt(value: Any) -> Any:
    """Return a value guaranteed to differ from ``value`` (so the seeded claim FAILs).

    Kept type-appropriate so the false ``expected`` still looks like a plausible answer
    a confident agent might assert — not obviously a sabotage sentinel.
    """
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1
    if isinstance(value, float):
        return value + 1.0
    if isinstance(value, str):
        return value + "_x"
    if isinstance(value, (list, tuple)):
        seq = list(value)
        return list(reversed(seq)) if len(seq) > 1 else seq + ["x"]
    return "definitely-wrong"


def _seed_false_claim(symbol: SymbolInfo) -> Optional[Claim]:
    """Build ONE guaranteed-false but well-formed claim about ``symbol``.

    Prefers an ``ExampleClaim`` derived from the symbol's first ``>>>`` doctest with the
    expected value corrupted — the most visceral demo, because the sandbox *executes* the
    real function and returns the true counterexample. Falls back to a deliberately wrong
    ``SignatureClaim`` (an extra bogus parameter) for symbols with no usable doctest, so the
    seed works on any target. Returns ``None`` only if even that can't be built.
    """
    if symbol.docstring:
        for ex in doctest.DocTestParser().get_examples(symbol.docstring):
            try:
                call = ast.parse(ex.source.strip(), mode="eval").body
            except (SyntaxError, ValueError):
                continue
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)):
                continue
            if call.func.id != symbol.name:
                continue  # e.g. `round(circle_area(1), 4)` — not a direct call
            try:
                args = [ast.literal_eval(a) for a in call.args]
                kwargs = {kw.arg: ast.literal_eval(kw.value) for kw in call.keywords if kw.arg}
                true_val = ast.literal_eval(ex.want.strip())
            except (ValueError, SyntaxError):
                continue
            wrong = _corrupt(true_val)
            arg_str = ", ".join(repr(a) for a in args)
            return ExampleClaim(
                type="example",
                target=symbol.name,
                prose=f"{symbol.name}({arg_str}) returns {wrong!r}.",
                cases=[ExampleCase(args=args, kwargs=kwargs, expected=wrong)],
            )

    # Fallback: a wrong signature (real signature + a phantom parameter). The signature
    # lane AST-diffs it against reality → mismatch → FAIL, deterministically.
    if symbol.signature.startswith("(") and ")" in symbol.signature:
        bogus = symbol.signature.replace(")", ", _phantom)", 1)
    else:
        bogus = "(_phantom)"
    return SignatureClaim(
        type="signature",
        target=symbol.name,
        prose=f"{symbol.name} takes an extra `_phantom` parameter.",
        claimed_signature=bogus,
    )


class SeededWorker(Worker):
    """Demo worker: plant a guaranteed-false claim first, let a real model correct it.

    On the **first** attempt (``feedback is None``) it returns a single, deliberately wrong
    claim about the symbol (see ``_seed_false_claim``) — so the harness's FAIL → alarm → retry
    path *always* fires, no matter how capable the model is. On every **subsequent** attempt
    it delegates to the wrapped ``inner`` worker, which now sees the harness's counterexample
    as feedback and regenerates true claims that verify and ship.

    This makes the catch-and-recover arc deterministic for demos without depending on a weak
    model being fooled by a misleading docstring: the lie is injected, a real LLM fixes it.

    ``bypass_replay_cache`` tells the loop not to serve a cached PASS for this run: the cache
    is keyed by ``(symbol, lane, code_hash)``, so a PASS cached from an earlier honest run on
    the same module would otherwise mask the seeded false claim (same lane, same code) and the
    lie would never be caught. Bypassing keeps the demo deterministic on a shared backend.
    """

    #: Read by ``harness.run`` — see the class docstring.
    bypass_replay_cache = True

    def __init__(self, inner: Worker) -> None:
        self._inner = inner

    def generate(
        self, symbol: SymbolInfo, feedback: Optional[list[Alarm]] = None
    ) -> list[Claim]:
        if feedback is None:
            seed = _seed_false_claim(symbol)
            if seed is not None:
                return [seed]
        return self._inner.generate(symbol, feedback)
