"""Material renderer — turn verified claims into markdown with ✓ receipts.

Every ✓ in the rendered output is backed by a ``CheckpointResult`` that passed
verification. ``DescriptionClaim`` text renders under "Notes (unverified)" without a ✓
— it is never proven, by design (design.md §1 / §4).

Public API
----------
render_doc(symbol, passing_pairs) -> str
    Render a single-symbol verified-doc markdown string.

render_index(documented_symbols) -> str
    Render a short index listing all documented symbols.

The rendered documents are a *projection* of the audit trail, not the source of truth
(design.md §8). The real receipts live in ``runs/<id>/checkpoints/``.
"""

from __future__ import annotations

from typing import Sequence

from harness.contracts import (
    BehavioralClaim,
    CheckpointResult,
    Claim,
    DescriptionClaim,
    ExampleClaim,
    SignatureClaim,
    SymbolInfo,
)

__all__ = ["render_doc", "render_index"]

# ── internal helpers ──────────────────────────────────────────────────────────


def _receipt(result: CheckpointResult) -> str:
    """One-line receipt: ``lane · hash_prefix · timestamp``."""
    ts = result.timestamp
    return f"{result.lane} · {result.code_hash[:8]} · {ts}"


def _render_signature_section(
    claim: SignatureClaim,
    result: CheckpointResult,
) -> str:
    lines = [
        "## Signature",
        "",
        f"```python",
        f"def {claim.target}{claim.claimed_signature}",
        "```",
        "",
        f"✓ _Verified — {_receipt(result)}_",
        "",
    ]
    return "\n".join(lines)


def _render_examples_section(
    claim: ExampleClaim,
    result: CheckpointResult,
) -> str:
    lines = ["## Usage", ""]
    for case in claim.cases:
        args_repr = ", ".join(repr(a) for a in case.args)
        kwargs_repr = ", ".join(f"{k}={v!r}" for k, v in (case.kwargs or {}).items())
        call_args = ", ".join(filter(None, [args_repr, kwargs_repr]))
        lines.append(f"```python")
        lines.append(f"{claim.target}({call_args})  # → {case.expected!r}")
        lines.append("```")
        lines.append("")
    lines.append(f"✓ _Verified — {_receipt(result)}_")
    lines.append("")
    return "\n".join(lines)


def _render_behavioral_section(
    claim: BehavioralClaim,
    result: CheckpointResult,
) -> str:
    lines = ["## Verified behavior", ""]
    lines.append(f"_{claim.prose}_")
    lines.append("")
    for snippet in claim.asserts:
        lines.append(f"```python")
        lines.append(snippet)
        lines.append("```")
        lines.append("")
    lines.append(f"✓ _Verified — {_receipt(result)}_")
    lines.append("")
    return "\n".join(lines)


def _render_description_section(claim: DescriptionClaim) -> str:
    lines = [
        "## Notes (unverified)",
        "",
        claim.prose,
        "",
    ]
    return "\n".join(lines)


# ── public API ────────────────────────────────────────────────────────────────


def render_doc(
    symbol: SymbolInfo,
    passing_pairs: Sequence[tuple[Claim, CheckpointResult]],
) -> str:
    """Render a verified-doc markdown string for *symbol*.

    Parameters
    ----------
    symbol:
        The ``SymbolInfo`` extracted by the loader.
    passing_pairs:
        Pairs of ``(Claim, CheckpointResult)`` where each result has
        ``verdict == Verdict.PASS``. Description claims may be paired with any
        result (or ``None`` — callers should pass a sentinel; see below).

    Returns
    -------
    str
        Markdown string. Each verifiable claim section ends with a ✓ receipt.
        ``DescriptionClaim`` sections render under "Notes (unverified)" with no ✓.
    """
    sections: list[str] = []

    # Document header.
    sections.append(f"# `{symbol.name}`")
    sections.append("")
    if symbol.docstring:
        sections.append(symbol.docstring)
        sections.append("")
    sections.append(f"**Signature:** `{symbol.signature}`  ")
    sections.append(f"Line {symbol.lineno} · hash `{symbol.code_hash[:8]}`")
    sections.append("")

    # Separate descriptions from verifiable claims.
    description_claims: list[DescriptionClaim] = []
    verifiable_pairs: list[tuple[Claim, CheckpointResult]] = []

    for claim, result in passing_pairs:
        if isinstance(claim, DescriptionClaim):
            description_claims.append(claim)
        else:
            verifiable_pairs.append((claim, result))

    # Render verifiable sections with ✓ receipts.
    for claim, result in verifiable_pairs:
        if isinstance(claim, SignatureClaim):
            sections.append(_render_signature_section(claim, result))
        elif isinstance(claim, ExampleClaim):
            sections.append(_render_examples_section(claim, result))
        elif isinstance(claim, BehavioralClaim):
            sections.append(_render_behavioral_section(claim, result))

    # Render description claims without ✓.
    for claim in description_claims:
        sections.append(_render_description_section(claim))

    return "\n".join(sections)


def render_index(documented_symbols: Sequence[SymbolInfo]) -> str:
    """Render a brief index markdown listing all documented symbols.

    Parameters
    ----------
    documented_symbols:
        Sequence of ``SymbolInfo`` objects for each symbol that has a rendered doc.

    Returns
    -------
    str
        Markdown index with one row per symbol.
    """
    lines = [
        "# Index",
        "",
        "Symbols verified and documented in this run:",
        "",
    ]

    if not documented_symbols:
        lines.append("_No symbols documented._")
        lines.append("")
    else:
        lines.append("| Symbol | Signature | Line |")
        lines.append("|--------|-----------|------|")
        for sym in documented_symbols:
            lines.append(f"| `{sym.name}` | `{sym.signature}` | {sym.lineno} |")
        lines.append("")

    return "\n".join(lines)
