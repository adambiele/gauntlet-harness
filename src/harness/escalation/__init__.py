"""Escalation package — routes INCONCLUSIVE and retry-exhausted claims to human triage.

Exports the abstract ``EscalationHandler`` and the concrete ``BatchHandler`` used by the
loop (``harness.py``) to accumulate escalated claims in memory and persist them to
``escalations.jsonl`` via the store. ``triage_list()`` returns the accumulated records for
the end-of-run summary and the dashboard triage panel.
"""

from harness.escalation.handlers import BatchHandler, EscalationHandler

__all__ = ["EscalationHandler", "BatchHandler"]
