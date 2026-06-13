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

from abc import ABC, abstractmethod
from typing import Optional

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

__all__ = ["Worker", "StubWorker"]


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
