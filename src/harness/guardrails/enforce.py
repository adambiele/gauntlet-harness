"""Guardrail enforcement — apply all declared rules before verification (design.md §6).

Entry point::

    cleaned_claims, alarms = enforce(claims, ctx)

``enforce`` runs deterministically before the verification lanes. Violations produce
``Alarm`` objects (BLOCK-severity → claim dropped; non-BLOCK → claim still proceeds
unless it is structurally unsound). The caller is responsible for routing alarms
(A4 emit, B loop).

Span: wraps the entire call in ``SPAN_GATE`` so the OTel tree is
``run → symbol → gate``.
"""

from __future__ import annotations

import ast
import re
from datetime import datetime, timezone
from typing import Any

from harness.alarms.types import (
    BEHAVIOR_CONTRADICTION,
    MALFORMED_CLAIM,
    PHANTOM_API,
    SECRET_LEAK,
    Alarm,
    AlarmType,
)
from harness.contracts import (
    BehavioralClaim,
    Claim,
    CodeContext,
    DescriptionClaim,
    ExampleClaim,
)
from harness.observability import SPAN_GATE, span

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SECRET_PATTERNS: list[re.Pattern[str]] = [
    # Long hex strings (≥32 hex chars) — common for API keys / hashes
    re.compile(r"[0-9a-fA-F]{32,}"),
    # Base64-ish blobs (≥32 chars of base64 alphabet)
    re.compile(r"[A-Za-z0-9+/]{32,}={0,2}"),
    # Key-indicator prefix patterns (case-insensitive)
    re.compile(r"(?i)(sk|pk|api[_-]?key|token|secret|password|passwd|apikey|bearer)[_\-\s:=]+\S{8,}"),
]

_ABS_PATH_PATTERN = re.compile(
    r"(^|[\s\"'`(,=])"     # word boundary / start-of-string / common delimiters
    r"("
    r"/[^\s\"'`,)]{8,}"    # Unix absolute path (≥ "/" + 8 chars)
    r"|"
    r"[A-Za-z]:\\[^\s\"'`,)]{4,}"  # Windows absolute path
    r")"
)

# Dangerous call names that are always rejected in snippets.
_DANGEROUS_CALLS: frozenset[str] = frozenset({"eval", "exec", "open", "__import__"})


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _make_alarm(
    alarm_type: AlarmType,
    symbol: str,
    message: str,
    claim_ref: str | None = None,
) -> Alarm:
    """Construct an Alarm by copying severity/recommended_action from the AlarmType."""
    return Alarm(
        type=alarm_type.name,
        severity=alarm_type.severity,
        symbol=symbol,
        claim_ref=claim_ref,
        message=message,
        recommended_action=alarm_type.recommended_action,
        timestamp=_now_iso(),
    )


def _claim_ref(claim: Any) -> str:
    """Return a short human-readable reference for a claim."""
    return f"{getattr(claim, 'type', '?')}:{getattr(claim, 'target', '?')}"


# ---------------------------------------------------------------------------
# Secret / path scanner
# ---------------------------------------------------------------------------

def _collect_text_fields(claim: Any) -> list[str]:
    """Extract all text fields from a claim for secret scanning."""
    fields: list[str] = []
    for attr in ("prose", "claimed_signature"):
        val = getattr(claim, attr, None)
        if isinstance(val, str):
            fields.append(val)
    # BehavioralClaim snippets
    asserts = getattr(claim, "asserts", None)
    if isinstance(asserts, list):
        for s in asserts:
            if isinstance(s, str):
                fields.append(s)
    return fields


def _has_secret(text: str) -> bool:
    """Return True if the text contains a key-like string or absolute path."""
    for pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            return True
    if _ABS_PATH_PATTERN.search(text):
        return True
    return False


def _check_secret_leak(claim: Any) -> str | None:
    """Return a description of the leak if found, else None."""
    for text in _collect_text_fields(claim):
        if _has_secret(text):
            return f"possible secret or absolute path detected in claim text"
    return None


# ---------------------------------------------------------------------------
# AST snippet vetter
# ---------------------------------------------------------------------------

class _SnippetVetError(Exception):
    """Raised by the AST vetter when a snippet fails."""
    pass


class _AllowlistVisitor(ast.NodeVisitor):
    """AST visitor that enforces the behavioral snippet allowlist.

    IMPORTANT: This is a declared guardrail + fast-reject, NOT the security boundary.
    See rules.py for the full security model note.
    """

    def __init__(self, target_name: str) -> None:
        self.target_name = target_name
        self.has_assert = False
        self.references_target = False

    def visit_Import(self, node: ast.Import) -> None:
        raise _SnippetVetError("import statement not allowed in behavioral snippet")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        raise _SnippetVetError("from-import statement not allowed in behavioral snippet")

    def visit_Call(self, node: ast.Call) -> None:
        # Reject calls to dangerous builtins by name
        if isinstance(node.func, ast.Name) and node.func.id in _DANGEROUS_CALLS:
            raise _SnippetVetError(
                f"call to '{node.func.id}' is not allowed in behavioral snippet"
            )
        # Also reject as attribute (e.g. builtins.eval)
        if isinstance(node.func, ast.Attribute) and node.func.attr in _DANGEROUS_CALLS:
            raise _SnippetVetError(
                f"call to '.{node.func.attr}' is not allowed in behavioral snippet"
            )
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # Reject dunder attribute access
        attr = node.attr
        if attr.startswith("__") and attr.endswith("__"):
            raise _SnippetVetError(
                f"dunder attribute access '{attr}' is not allowed in behavioral snippet"
            )
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id == self.target_name:
            self.references_target = True
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert) -> None:
        self.has_assert = True
        self.generic_visit(node)


def _vet_snippet(snippet: str, target_name: str) -> str | None:
    """Vet a single snippet.  Returns an error message or None if clean."""
    try:
        tree = ast.parse(snippet, mode="exec")
    except SyntaxError as exc:
        return f"snippet has a syntax error: {exc}"

    visitor = _AllowlistVisitor(target_name)
    try:
        visitor.visit(tree)
    except _SnippetVetError as exc:
        return str(exc)

    if not visitor.references_target:
        return f"snippet does not reference the target symbol '{target_name}'"

    return None  # clean


def _snippets_have_assert(snippets: list[str]) -> bool:
    """Return True iff at least one snippet contains an assert statement."""
    for snippet in snippets:
        try:
            tree = ast.parse(snippet, mode="exec")
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert):
                return True
    return False


# ---------------------------------------------------------------------------
# Per-rule checks (return list of alarms; may modify the claim list)
# ---------------------------------------------------------------------------

def _check_target_exists(
    claim: Any, ctx: CodeContext
) -> list[Alarm]:
    target = getattr(claim, "target", None)
    if target is None or target not in ctx.symbols:
        return [_make_alarm(
            PHANTOM_API,
            symbol=str(target or ""),
            message=f"claim target '{target}' is not in CodeContext.symbols",
            claim_ref=_claim_ref(claim),
        )]
    return []


def _check_example_valid(claim: ExampleClaim) -> list[Alarm]:
    alarms: list[Alarm] = []
    if not claim.cases:
        alarms.append(_make_alarm(
            MALFORMED_CLAIM,
            symbol=claim.target,
            message="ExampleClaim has no cases — nothing to verify",
            claim_ref=_claim_ref(claim),
        ))
        return alarms
    for i, case in enumerate(claim.cases):
        if not isinstance(case.args, list):
            alarms.append(_make_alarm(
                MALFORMED_CLAIM,
                symbol=claim.target,
                message=f"ExampleCase[{i}].args is not a list (got {type(case.args).__name__})",
                claim_ref=_claim_ref(claim),
            ))
        if not isinstance(case.kwargs, dict):
            alarms.append(_make_alarm(
                MALFORMED_CLAIM,
                symbol=claim.target,
                message=f"ExampleCase[{i}].kwargs is not a dict (got {type(case.kwargs).__name__})",
                claim_ref=_claim_ref(claim),
            ))
    return alarms


def _check_behavioral_snippets(
    claim: BehavioralClaim,
) -> tuple[Claim, list[Alarm]]:
    """Vet behavioral snippets.  May return a downgraded DescriptionClaim."""
    alarms: list[Alarm] = []

    for snippet in claim.asserts:
        err = _vet_snippet(snippet, claim.target)
        if err:
            alarms.append(_make_alarm(
                BEHAVIOR_CONTRADICTION,
                symbol=claim.target,
                message=f"snippet failed AST allowlist vetting: {err}",
                claim_ref=_claim_ref(claim),
            ))
            # Claim is dropped via BLOCK severity — caller handles this.
            return claim, alarms

    # Check for ≥1 assert across all snippets
    if not _snippets_have_assert(claim.asserts):
        # Downgrade to DescriptionClaim (no alarm — silent downgrade per spec)
        downgraded = DescriptionClaim(
            type="description",
            target=claim.target,
            prose=claim.prose,
        )
        return downgraded, alarms

    return claim, alarms


# ---------------------------------------------------------------------------
# Main enforce function
# ---------------------------------------------------------------------------

def enforce(
    claims: list[Claim],
    ctx: CodeContext,
) -> tuple[list[Claim], list[Alarm]]:
    """Apply all guardrail rules to *claims* before verification.

    Returns ``(cleaned_claims, alarms)`` where:
    - ``cleaned_claims`` — claims that passed all rules (BLOCK violations → dropped;
      BehavioralClaims with no asserts → downgraded to DescriptionClaim).
    - ``alarms`` — all Alarm objects raised (caller routes to emit/store).

    Wrapped in ``span(SPAN_GATE)`` for OTel (run → symbol → gate).
    """
    with span(SPAN_GATE):
        cleaned: list[Claim] = []
        all_alarms: list[Alarm] = []

        for claim in claims:
            drop = False
            current_claim: Claim = claim

            # ── Rule 1: target exists ──────────────────────────────────────
            target_alarms = _check_target_exists(claim, ctx)
            if target_alarms:
                all_alarms.extend(target_alarms)
                drop = True  # PHANTOM_API is BLOCK severity

            if drop:
                continue  # no point checking further rules on a dropped claim

            # ── Rule 2: secret leak (check early — BLOCK if found) ─────────
            leak_msg = _check_secret_leak(claim)
            if leak_msg:
                all_alarms.append(_make_alarm(
                    SECRET_LEAK,
                    symbol=claim.target,
                    message=leak_msg,
                    claim_ref=_claim_ref(claim),
                ))
                continue  # SECRET_LEAK is BLOCK — drop

            # ── Rule 3: example valid ──────────────────────────────────────
            if isinstance(claim, ExampleClaim):
                example_alarms = _check_example_valid(claim)
                if example_alarms:
                    all_alarms.extend(example_alarms)
                    # MALFORMED_CLAIM is HIGH (not BLOCK) — still drop structurally
                    # invalid examples because they cannot be verified.
                    continue

            # ── Rule 4: behavioral snippet vetting ────────────────────────
            if isinstance(claim, BehavioralClaim):
                current_claim, behavioral_alarms = _check_behavioral_snippets(claim)
                all_alarms.extend(behavioral_alarms)
                if behavioral_alarms:
                    # BEHAVIOR_CONTRADICTION is BLOCK — drop claim
                    continue
                # current_claim may be a downgraded DescriptionClaim here

            cleaned.append(current_claim)

        return cleaned, all_alarms
