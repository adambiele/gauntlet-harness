"""Signature checkpoint lane — structural AST diff, no execution (design.md §4b).

Parses both the claimed signature and the real signature via ``ast``, then compares
each component (params: name / annotation / default, and return annotation) individually.
This gives rich, actionable evidence that names the differing component rather than just
"mismatch".

No subprocess is spawned. This lane is purely deterministic.
"""

from __future__ import annotations

import ast
import time
from typing import Optional

from harness.contracts import CheckpointResult, SignatureClaim, SymbolInfo, Verdict

__all__ = ["check_signature"]

# Lane identifier used in CheckpointResult.lane and span names.
LANE = "signature"


def _parse_sig(sig: str) -> Optional[ast.arguments]:
    """Parse a signature string like ``(x: int, y: int = 0) -> int``.

    Returns ``(arguments_node, return_node_or_None)`` on success, or raises
    ``SyntaxError`` if the string is malformed.  We reconstruct a fake function
    definition so that the standard ``ast.parse`` can handle it.
    """
    src = f"def _(  {sig}): pass"
    try:
        tree = ast.parse(src, mode="exec")
    except SyntaxError:
        # Try wrapping without extra spaces in case the sig already starts with (
        src = f"def _{sig}: pass"
        tree = ast.parse(src, mode="exec")
    func: ast.FunctionDef = tree.body[0]  # type: ignore[assignment]
    return func.args, func.returns


def _ann_str(node: Optional[ast.expr]) -> str:
    """Render an annotation node to a normalised string (or '' if absent)."""
    if node is None:
        return ""
    return ast.unparse(node)


def _default_str(node: Optional[ast.expr]) -> str:
    """Render a default node to a normalised string (or '<no default>' if absent)."""
    if node is None:
        return "<no default>"
    return ast.unparse(node)


def _param_defaults(args: ast.arguments) -> dict[str, Optional[ast.expr]]:
    """Return a mapping of param_name → default AST node (None if no default).

    ``ast.arguments`` stores defaults right-aligned against the positional list, so we
    need to align them.
    """
    all_params = args.posonlyargs + args.args
    n_params = len(all_params)
    n_defaults = len(args.defaults)
    # Defaults are right-aligned.
    defaults: list[Optional[ast.expr]] = [None] * (n_params - n_defaults) + list(args.defaults)
    return {param.arg: default for param, default in zip(all_params, defaults)}


def check_signature(
    claim: SignatureClaim,
    symbol: SymbolInfo,
    _module_source: str = "",  # unused; present for uniform lane call signature
) -> CheckpointResult:
    """Run the signature lane: structural diff of claim vs real signature.

    Returns a ``CheckpointResult`` with:
    * ``verdict=PASS`` when claim and reality agree exactly.
    * ``verdict=FAIL`` when any component differs; ``evidence`` names the component.
    * ``verdict=FAIL`` if either signature is unparseable (with parse error in evidence).
    """
    import datetime

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

    # -- parse both signatures --------------------------------------------------
    try:
        real_args, real_return = _parse_sig(symbol.signature)
    except SyntaxError as exc:
        return _result(Verdict.FAIL, f"could not parse real signature {symbol.signature!r}: {exc}")

    try:
        claim_args, claim_return = _parse_sig(claim.claimed_signature)
    except SyntaxError as exc:
        return _result(Verdict.FAIL, f"could not parse claimed signature {claim.claimed_signature!r}: {exc}")

    diffs: list[str] = []

    # -- compare positional + pos-only params (name, annotation, default) --------
    real_params = real_args.posonlyargs + real_args.args
    claim_params = claim_args.posonlyargs + claim_args.args
    real_defaults = _param_defaults(real_args)
    claim_defaults = _param_defaults(claim_args)

    real_names = [p.arg for p in real_params]
    claim_names = [p.arg for p in claim_params]

    if real_names != claim_names:
        diffs.append(
            f"param list: real has {real_names!r}, claim has {claim_names!r}"
        )
    else:
        # Same names — check annotation and default per-param.
        for r_param, c_param in zip(real_params, claim_params):
            name = r_param.arg
            r_ann = _ann_str(r_param.annotation)
            c_ann = _ann_str(c_param.annotation)
            if r_ann != c_ann:
                diffs.append(
                    f"param `{name}`: real annotation `{r_ann or '<none>'}`, "
                    f"claim says `{c_ann or '<none>'}`"
                )
            r_def = _default_str(real_defaults.get(name))
            c_def = _default_str(claim_defaults.get(name))
            if r_def != c_def:
                diffs.append(
                    f"param `{name}`: real default `{r_def}`, claim says `{c_def}`"
                )

    # -- compare *args and **kwargs names (vararg / kwarg) -----------------------
    def _vararg_name(arg: Optional[ast.arg]) -> str:
        return arg.arg if arg is not None else "<none>"

    r_var = _vararg_name(real_args.vararg)
    c_var = _vararg_name(claim_args.vararg)
    if r_var != c_var:
        diffs.append(f"*args: real `{r_var}`, claim says `{c_var}`")

    r_kw = _vararg_name(real_args.kwarg)
    c_kw = _vararg_name(claim_args.kwarg)
    if r_kw != c_kw:
        diffs.append(f"**kwargs: real `{r_kw}`, claim says `{c_kw}`")

    # -- compare return annotation -----------------------------------------------
    r_ret = _ann_str(real_return)
    c_ret = _ann_str(claim_return)
    if r_ret != c_ret:
        diffs.append(
            f"return annotation: real `{r_ret or '<none>'}`, claim says `{c_ret or '<none>'}`"
        )

    if diffs:
        evidence = "; ".join(diffs)
        return _result(Verdict.FAIL, evidence)

    return _result(Verdict.PASS, "signature matches")
