"""Declared, printable guardrail rule set (design.md §4b, §6).

Rules here are documentation *and* the source of truth that ``enforce.py`` implements.
Each ``Rule`` has a human-readable description so the rule set can be printed / surfaced
in the dashboard without needing to read source code.

IMPORTANT — Security model note
================================
The BEHAVIORAL snippet-vetting rule (``behavioral_ast_allowlist``) uses an **AST-walk
allowlist** to reject obvious bad patterns: ``import``/``from import`` statements, calls
to ``eval``/``exec``/``open``/``__import__``, and dunder attribute access.

This is a **declared guardrail and fast-reject**, NOT the security boundary.

Python AST allowlists are escapable in many ways (e.g. ``getattr(builtins, 'eval')``).
The real security boundary is the **subprocess sandbox** (``checkpoints/sandbox.py``):
each behavioral snippet runs in a separate interpreter with a timeout and isolated
working directory. The AST check catches the obvious/accidental cases cheaply and
provides an audit trail; the sandbox catches everything else.

Do NOT relax the subprocess sandbox on the assumption the AST check is sufficient.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    """A single declared guardrail rule.

    ``name``     — machine identifier (matches alarm type name where applicable).
    ``summary``  — one-line description for dashboards / reports.
    ``detail``   — full specification of what is checked.
    """

    name: str
    summary: str
    detail: str


# ---------------------------------------------------------------------------
# The rule set — each rule maps to enforcement logic in enforce.py
# ---------------------------------------------------------------------------

TARGET_EXISTS = Rule(
    name="TARGET_EXISTS",
    summary="Claim target must be a known symbol in the CodeContext.",
    detail=(
        "claim.target must appear in ctx.symbols. If it does not, the claim references a "
        "symbol the harness cannot verify — emit PHANTOM_API alarm and drop the claim."
    ),
)

EXAMPLE_VALID = Rule(
    name="EXAMPLE_VALID",
    summary="ExampleClaim must have ≥1 case; each case's args must be a list and kwargs a dict.",
    detail=(
        "An ExampleClaim with no cases has nothing to verify. Each ExampleCase.args must be "
        "a list and each ExampleCase.kwargs must be a dict, because the harness builds the "
        "call as target(*args, **kwargs). Malformed cases → MALFORMED_CLAIM alarm."
    ),
)

BEHAVIORAL_SNIPPET_VETTING = Rule(
    name="BEHAVIORAL_SNIPPET_VETTING",
    summary=(
        "BehavioralClaim snippets are AST-vetted (fast-reject) and must reference the target "
        "and contain ≥1 assert. No-assert claims are downgraded to DescriptionClaim."
    ),
    detail=(
        "AST-walk allowlist (declared guardrail + fast-reject — NOT the security boundary; "
        "the subprocess sandbox is): "
        "(1) Reject any Import or ImportFrom node — imports are not allowed in snippets. "
        "(2) Reject calls to eval, exec, open, __import__ by name. "
        "(3) Reject dunder attribute access (attribute names starting and ending with '__'). "
        "(4) Require the snippet to reference the target symbol by name (at least one Name "
        "    node matching claim.target). "
        "Additionally: if the snippet set contains zero 'assert' statements across all "
        "snippets, the BehavioralClaim is downgraded to a DescriptionClaim (no MALFORMED "
        "alarm — downgrade is silent but logged via the returned claim list). "
        "A snippet that fails the AST allowlist check → BEHAVIOR_CONTRADICTION alarm and "
        "the claim is dropped."
    ),
)

SECRET_LEAK = Rule(
    name="SECRET_LEAK",
    summary="No key-like strings or absolute paths in prose or snippets.",
    detail=(
        "Scan all string fields (prose, snippets, claimed_signature) for patterns that look "
        "like secrets or local machine paths: "
        "(1) Key-like strings: sequences matching common secret patterns — long hex strings "
        "    (≥32 hex chars), base64-ish blobs (≥32 chars of [A-Za-z0-9+/=]), strings "
        "    containing common key indicators (sk-, pk-, api_key, token, secret, password, "
        "    passwd, apikey, bearer) adjacent to a value. "
        "(2) Absolute paths: strings starting with '/' (Unix) or matching '[A-Za-z]:\\\\' "
        "    (Windows) that are ≥10 chars (to avoid false positives on short root paths). "
        "Violation → SECRET_LEAK alarm; claim is dropped."
    ),
)

# All rules in declaration order — usable for documentation / dashboard rendering.
RULES: list[Rule] = [
    TARGET_EXISTS,
    EXAMPLE_VALID,
    BEHAVIORAL_SNIPPET_VETTING,
    SECRET_LEAK,
]
