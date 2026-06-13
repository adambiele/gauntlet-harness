"""Guardrails — declared, deterministic checks that run BEFORE verification (design.md §6).

The guardrail layer is a pillar: cheap, explicitly documented, and separate from the
worker. It rejects or downgrades claims that are structurally unsafe or unsound
*before* any subprocess sandbox work starts.

Public API::

    from harness.guardrails import enforce
    from harness.guardrails.rules import RULES

``enforce(claims, ctx)`` is the single entry point. ``RULES`` is the printable rule set.
"""

from harness.guardrails.enforce import enforce

__all__ = ["enforce"]
