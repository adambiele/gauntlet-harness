"""Escalation handlers — triage queue for INCONCLUSIVE and retry-exhausted claims.

The loop (``harness.py``) calls ``handler.handle(...)`` for every claim that cannot be
resolved automatically: ``INCONCLUSIVE`` verdicts (e.g. ``DescriptionClaim``) and claims
still FAIL after the maximum retry count. Each call:

1. Appends a self-describing record to ``escalations.jsonl`` via the store so the audit
   trail is always on disk.
2. Accumulates the record in memory so ``triage_list()`` can return the full set at run-end
   for the summary and the dashboard triage panel.

Optionally, ``BatchHandler`` can emit a :class:`~harness.adapters.events.ClaimEscalated`
SSE event for live streaming — use ``to_event(record)`` to obtain the event.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

from harness.adapters.events import ClaimEscalated
from harness.contracts import Claim
from harness.persistence.store import Store

__all__ = ["EscalationHandler", "BatchHandler", "to_event"]


def _claim_summary(claim: Claim) -> str:
    """Return a short, human-readable summary of a claim for triage records."""
    claim_type = getattr(claim, "type", "unknown")
    prose = getattr(claim, "prose", "")
    # Truncate long prose to keep the record compact.
    if len(prose) > 120:
        prose = prose[:117] + "..."
    return f"[{claim_type}] {prose}" if prose else f"[{claim_type}]"


class EscalationHandler(ABC):
    """Abstract base for escalation handlers.

    A handler receives every claim the loop cannot resolve automatically and decides what
    to do with it (persist, queue, page on-call, etc.).  The loop calls :meth:`handle`
    once per escalated claim and :meth:`triage_list` at run-end to build the summary.
    """

    @abstractmethod
    def handle(
        self,
        run_id: str,
        symbol: str,
        claim: Claim,
        reason: str,
        store: Store,
    ) -> None:
        """Record one escalated claim.

        Args:
            run_id: The active run identifier (used to locate the store partition).
            symbol: The symbol the claim was generated for.
            claim:  The claim that could not be resolved — used to build a summary.
            reason: Human-readable explanation of why the claim was escalated (e.g.
                    ``"INCONCLUSIVE"`` or ``"retry exhausted after 3 attempts"``).
            store:  The active :class:`~harness.persistence.store.Store`; used to append
                    the escalation record to ``escalations.jsonl``.
        """

    @abstractmethod
    def triage_list(self) -> list[dict]:
        """Return the accumulated escalation records for this handler instance.

        Returned dicts are self-describing (symbol, claim_summary, reason, timestamp) and
        are safe to serialise directly to the dashboard triage panel or the run summary.
        """


class BatchHandler(EscalationHandler):
    """Batch escalation handler — accumulate → ``escalations.jsonl`` + in-memory triage list.

    This is the default handler used by the loop.  Each :meth:`handle` call:

    * Builds a self-describing record with the symbol, a brief claim summary, the reason,
      and a UTC timestamp.
    * Appends the record to ``escalations.jsonl`` via
      :meth:`~harness.persistence.store.Store.append_escalation`.
    * Stores the record in :attr:`_records` so :meth:`triage_list` can return them later.

    The handler is **not** thread-safe — the loop is sequential (design.md §6), so this is
    fine for the sprint.
    """

    def __init__(self) -> None:
        self._records: list[dict] = []

    def handle(
        self,
        run_id: str,
        symbol: str,
        claim: Claim,
        reason: str,
        store: Store,
    ) -> None:
        """Escalate one claim: persist to ``escalations.jsonl`` and accumulate in memory.

        Args:
            run_id: The active run identifier.
            symbol: The symbol the claim belongs to.
            claim:  The unresolved claim.
            reason: Why this claim is being escalated.
            store:  The active store for this run.
        """
        record: dict = {
            "symbol": symbol,
            "claim_summary": _claim_summary(claim),
            "reason": reason,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        }
        store.append_escalation(run_id, record)
        self._records.append(record)

    def triage_list(self) -> list[dict]:
        """Return a copy of all escalation records accumulated during this run.

        Each record is a plain ``dict`` with keys ``symbol``, ``claim_summary``,
        ``reason``, and ``timestamp``.  The list is in insertion order (i.e. the order
        the claims were escalated).
        """
        return list(self._records)


def to_event(record: dict) -> ClaimEscalated:
    """Convert an escalation record dict to a :class:`~harness.adapters.events.ClaimEscalated` SSE event.

    This is a convenience helper for callers that want to stream an escalation to the
    dashboard immediately after calling :meth:`BatchHandler.handle`.

    Args:
        record: A record as produced by :meth:`BatchHandler.handle` — must contain
                ``symbol`` and ``reason`` keys.

    Returns:
        A :class:`~harness.adapters.events.ClaimEscalated` event ready for
        :func:`~harness.adapters.events.to_sse`.
    """
    return ClaimEscalated(
        symbol=record["symbol"],
        reason=record["reason"],
    )
