"""Tests for harness.material — loader and renderer.

Covers:
- loader extracts public top-level plain def functions without importing the module
- loader skips private, async, decorated functions
- code_hash is stable across comment/whitespace changes
- code_hash changes on structural edits
- SyntaxError in target → empty symbols, no crash
- OSError (file not found) → empty symbols, no crash
- renderer: signature claims → ✓ receipt
- renderer: example claims → ✓ receipt with call representation
- renderer: behavioral claims → ✓ receipt
- renderer: description claims → "Notes (unverified)" section, NO ✓
- renderer: mixed passing_pairs → only verifiable claims get ✓
- render_index: lists documented symbols in a table
"""

import textwrap
from pathlib import Path

import pytest

from harness.contracts import (
    BehavioralClaim,
    CheckpointResult,
    DescriptionClaim,
    ExampleCase,
    ExampleClaim,
    SignatureClaim,
    SymbolInfo,
    Verdict,
)
from harness.material.loader import load_module
from harness.material.renderer import render_doc, render_index


# ── fixtures ─────────────────────────────────────────────────────────────────

SAMPLE_MODULE = textwrap.dedent("""\
    \"\"\"A sample module for testing the loader.\"\"\"

    CONSTANT = 42


    def add(x: int, y: int = 0) -> int:
        \"\"\"Return the sum of x and y.\"\"\"
        return x + y


    def _private(x):
        return x


    async def async_fn(x):
        return x


    def decorated(x):
        return x


    decorated = staticmethod(decorated)


    class MyClass:
        def method(self):
            pass
""")

SAMPLE_WITH_DECORATOR = textwrap.dedent("""\
    import functools

    def plain(x):
        return x

    @functools.lru_cache
    def cached(x):
        return x
""")

SYNTAX_ERROR_MODULE = "def broken(:\n    pass\n"


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def _checkpoint(
    claim,
    lane: str = "example",
    code_hash: str = "abc123defabc123d",
    verdict: Verdict = Verdict.PASS,
) -> CheckpointResult:
    return CheckpointResult(
        symbol=claim.target,
        claim=claim,
        verdict=verdict,
        evidence="ok",
        code_hash=code_hash,
        lane=lane,
        timestamp="2026-06-13T12:00:00Z",
        duration_ms=1.5,
    )


# ── loader tests ──────────────────────────────────────────────────────────────


class TestLoader:
    def test_returns_code_context_with_module_path(self, tmp_path):
        p = _write(tmp_path, "sample.py", SAMPLE_MODULE)
        ctx = load_module(p)
        assert ctx.module_path == str(p)

    def test_module_source_is_full_file_text(self, tmp_path):
        p = _write(tmp_path, "sample.py", SAMPLE_MODULE)
        ctx = load_module(p)
        assert ctx.module_source == SAMPLE_MODULE

    def test_extracts_public_plain_def(self, tmp_path):
        p = _write(tmp_path, "sample.py", SAMPLE_MODULE)
        ctx = load_module(p)
        assert "add" in ctx.symbols

    def test_skips_private_function(self, tmp_path):
        p = _write(tmp_path, "sample.py", SAMPLE_MODULE)
        ctx = load_module(p)
        assert "_private" not in ctx.symbols

    def test_skips_async_function(self, tmp_path):
        p = _write(tmp_path, "sample.py", SAMPLE_MODULE)
        ctx = load_module(p)
        assert "async_fn" not in ctx.symbols

    def test_skips_decorated_function(self, tmp_path):
        p = _write(tmp_path, "with_decorator.py", SAMPLE_WITH_DECORATOR)
        ctx = load_module(p)
        assert "plain" in ctx.symbols
        assert "cached" not in ctx.symbols

    def test_does_not_extract_class_methods(self, tmp_path):
        p = _write(tmp_path, "sample.py", SAMPLE_MODULE)
        ctx = load_module(p)
        assert "method" not in ctx.symbols

    def test_symbol_info_fields(self, tmp_path):
        p = _write(tmp_path, "sample.py", SAMPLE_MODULE)
        ctx = load_module(p)
        info = ctx.symbols["add"]

        assert info.name == "add"
        # ast.unparse omits spaces around = for defaulted keyword args: "y: int=0"
        assert "x: int" in info.signature
        assert "y: int" in info.signature
        assert "-> int" in info.signature
        assert info.docstring == "Return the sum of x and y."
        assert info.lineno > 0
        assert info.source.startswith("def add")
        assert len(info.code_hash) == 64  # sha256 hex
        assert info.callable is None

    def test_signature_with_no_return_annotation(self, tmp_path):
        src = "def no_return(a, b):\n    return a + b\n"
        p = _write(tmp_path, "m.py", src)
        ctx = load_module(p)
        assert ctx.symbols["no_return"].signature == "(a, b)"

    def test_signature_with_return_annotation(self, tmp_path):
        src = "def typed(a: int) -> str:\n    return str(a)\n"
        p = _write(tmp_path, "m.py", src)
        ctx = load_module(p)
        assert ctx.symbols["typed"].signature == "(a: int) -> str"

    def test_docstring_none_when_absent(self, tmp_path):
        src = "def nodoc(x):\n    return x\n"
        p = _write(tmp_path, "m.py", src)
        ctx = load_module(p)
        assert ctx.symbols["nodoc"].docstring is None

    def test_never_imports_target(self, tmp_path):
        """Loader must work on a module whose import side-effects would raise."""
        src = textwrap.dedent("""\
            raise RuntimeError("do not import me")

            def safe(x):
                return x
        """)
        p = _write(tmp_path, "dangerous.py", src)
        # Must not raise — if it imported, RuntimeError would propagate.
        ctx = load_module(p)
        assert "safe" in ctx.symbols

    def test_syntax_error_returns_empty_symbols(self, tmp_path):
        p = _write(tmp_path, "bad.py", SYNTAX_ERROR_MODULE)
        ctx = load_module(p)
        assert ctx.symbols == {}
        assert ctx.module_path == str(p)

    def test_file_not_found_returns_empty_symbols(self, tmp_path):
        ctx = load_module(tmp_path / "nonexistent.py")
        assert ctx.symbols == {}

    def test_code_hash_stable_across_comment_change(self, tmp_path):
        """code_hash uses ast.unparse — comments are stripped, so hash must not change."""
        src_a = "def fn(x):\n    # first comment\n    return x\n"
        src_b = "def fn(x):\n    # totally different comment\n    return x\n"
        pa = _write(tmp_path, "a.py", src_a)
        pb = _write(tmp_path, "b.py", src_b)
        hash_a = load_module(pa).symbols["fn"].code_hash
        hash_b = load_module(pb).symbols["fn"].code_hash
        assert hash_a == hash_b, "code_hash must be stable across comment changes"

    def test_code_hash_stable_across_whitespace_change(self, tmp_path):
        """Extra blank lines should not change the hash."""
        src_a = "def fn(x):\n    return x\n"
        src_b = "def fn(x):\n\n    return x\n\n"
        pa = _write(tmp_path, "a.py", src_a)
        pb = _write(tmp_path, "b.py", src_b)
        hash_a = load_module(pa).symbols["fn"].code_hash
        hash_b = load_module(pb).symbols["fn"].code_hash
        assert hash_a == hash_b, "code_hash must be stable across whitespace changes"

    def test_code_hash_changes_on_structural_edit(self, tmp_path):
        """A real change (different body) must change the hash."""
        src_a = "def fn(x):\n    return x\n"
        src_b = "def fn(x):\n    return x + 1\n"
        pa = _write(tmp_path, "a.py", src_a)
        pb = _write(tmp_path, "b.py", src_b)
        hash_a = load_module(pa).symbols["fn"].code_hash
        hash_b = load_module(pb).symbols["fn"].code_hash
        assert hash_a != hash_b, "code_hash must change on structural edit"

    def test_code_hash_changes_on_docstring_edit(self, tmp_path):
        """Docstring is part of the AST body — editing it must change the hash."""
        src_a = 'def fn(x):\n    """Original docstring."""\n    return x\n'
        src_b = 'def fn(x):\n    """Changed docstring."""\n    return x\n'
        pa = _write(tmp_path, "a.py", src_a)
        pb = _write(tmp_path, "b.py", src_b)
        hash_a = load_module(pa).symbols["fn"].code_hash
        hash_b = load_module(pb).symbols["fn"].code_hash
        assert hash_a != hash_b, "code_hash must change when docstring changes"

    def test_multiple_functions_all_extracted(self, tmp_path):
        src = textwrap.dedent("""\
            def alpha(x):
                return x

            def beta(y):
                return y

            def _gamma(z):
                return z
        """)
        p = _write(tmp_path, "multi.py", src)
        ctx = load_module(p)
        assert set(ctx.symbols.keys()) == {"alpha", "beta"}

    def test_lineno_is_accurate(self, tmp_path):
        src = "# header\n\ndef fn(x):\n    return x\n"
        p = _write(tmp_path, "m.py", src)
        ctx = load_module(p)
        assert ctx.symbols["fn"].lineno == 3


# ── renderer tests ────────────────────────────────────────────────────────────


class TestRenderer:
    def _symbol(self, name: str = "add") -> SymbolInfo:
        return SymbolInfo(
            name=name,
            signature="(x: int, y: int) -> int",
            source=f"def {name}(x: int, y: int) -> int:\n    return x + y\n",
            docstring="Return x + y.",
            lineno=1,
            code_hash="abc123defabc123d" * 2,
        )

    def test_header_contains_symbol_name(self):
        sym = self._symbol("add")
        doc = render_doc(sym, [])
        assert "# `add`" in doc

    def test_docstring_appears_in_header(self):
        sym = self._symbol("add")
        doc = render_doc(sym, [])
        assert "Return x + y." in doc

    def test_signature_claim_renders_verified_receipt(self):
        sym = self._symbol("add")
        claim = SignatureClaim(
            type="signature", target="add", prose="add takes x and y",
            claimed_signature="(x: int, y: int) -> int",
        )
        result = _checkpoint(claim, lane="signature")
        doc = render_doc(sym, [(claim, result)])
        assert "## Signature" in doc
        assert "✓" in doc
        assert "signature" in doc
        assert result.code_hash[:8] in doc
        assert result.timestamp in doc

    def test_example_claim_renders_verified_receipt(self):
        sym = self._symbol("add")
        claim = ExampleClaim(
            type="example", target="add", prose="add(2, 3) == 5",
            cases=[ExampleCase(args=[2, 3], kwargs={}, expected=5)],
        )
        result = _checkpoint(claim, lane="example")
        doc = render_doc(sym, [(claim, result)])
        assert "## Usage" in doc
        assert "✓" in doc
        assert "example" in doc
        assert result.code_hash[:8] in doc

    def test_example_call_representation_in_doc(self):
        sym = self._symbol("add")
        claim = ExampleClaim(
            type="example", target="add", prose="test",
            cases=[ExampleCase(args=[1, 2], kwargs={}, expected=3)],
        )
        result = _checkpoint(claim, lane="example")
        doc = render_doc(sym, [(claim, result)])
        assert "add(1, 2)" in doc
        assert "3" in doc

    def test_behavioral_claim_renders_verified_receipt(self):
        sym = self._symbol("add")
        claim = BehavioralClaim(
            type="behavioral", target="add", prose="add is commutative",
            asserts=["assert add(1, 2) == add(2, 1)"],
        )
        result = _checkpoint(claim, lane="behavioral")
        doc = render_doc(sym, [(claim, result)])
        assert "## Verified behavior" in doc
        assert "✓" in doc
        assert "assert add(1, 2) == add(2, 1)" in doc
        assert result.code_hash[:8] in doc

    def test_description_claim_no_checkmark(self):
        sym = self._symbol("add")
        desc_claim = DescriptionClaim(
            type="description", target="add",
            prose="add is a simple arithmetic function.",
        )
        # Description claims don't have a CheckpointResult from verification,
        # but render_doc accepts any result object alongside them.
        # For the test, we use a sentinel checkpoint.
        sentinel = _checkpoint(
            SignatureClaim(type="signature", target="add", prose="p",
                           claimed_signature="(x, y)"),
            lane="description",
        )
        doc = render_doc(sym, [(desc_claim, sentinel)])
        assert "## Notes (unverified)" in doc
        assert "add is a simple arithmetic function." in doc
        # No ✓ should appear anywhere for description claims
        assert "✓" not in doc

    def test_description_claim_no_receipt(self):
        sym = self._symbol("add")
        desc_claim = DescriptionClaim(
            type="description", target="add", prose="Some description.",
        )
        sentinel = _checkpoint(
            SignatureClaim(type="signature", target="add", prose="p",
                           claimed_signature="(x, y)"),
            lane="description",
        )
        doc = render_doc(sym, [(desc_claim, sentinel)])
        # Timestamp and hash from the sentinel should NOT appear in the description section.
        assert sentinel.timestamp not in doc
        # But it's fine if the hash appears in the header (first 8 chars of symbol hash).

    def test_mixed_claims_only_verifiable_get_checkmark(self):
        sym = self._symbol("add")
        sig_claim = SignatureClaim(
            type="signature", target="add", prose="sig",
            claimed_signature="(x: int, y: int) -> int",
        )
        desc_claim = DescriptionClaim(
            type="description", target="add", prose="No verification possible.",
        )
        sig_result = _checkpoint(sig_claim, lane="signature")
        sentinel = _checkpoint(sig_claim, lane="signature")

        doc = render_doc(sym, [(sig_claim, sig_result), (desc_claim, sentinel)])
        assert "✓" in doc  # from signature
        assert "## Notes (unverified)" in doc
        # Count ✓ occurrences: only one (the signature claim)
        assert doc.count("✓") == 1

    def test_empty_passing_pairs_renders_header_only(self):
        sym = self._symbol("add")
        doc = render_doc(sym, [])
        assert "# `add`" in doc
        assert "✓" not in doc

    def test_render_index_empty(self):
        idx = render_index([])
        assert "# Index" in idx
        assert "No symbols documented." in idx

    def test_render_index_lists_symbols(self):
        syms = [
            SymbolInfo(
                name="add", signature="(x, y) -> int", source="", docstring=None,
                lineno=1, code_hash="a" * 64,
            ),
            SymbolInfo(
                name="subtract", signature="(x, y) -> int", source="", docstring=None,
                lineno=5, code_hash="b" * 64,
            ),
        ]
        idx = render_index(syms)
        assert "# Index" in idx
        assert "`add`" in idx
        assert "`subtract`" in idx
        assert "(x, y) -> int" in idx

    def test_receipt_format(self):
        """Receipt must include lane, 8-char code_hash prefix, and timestamp."""
        sym = self._symbol("add")
        claim = SignatureClaim(
            type="signature", target="add", prose="p",
            claimed_signature="(x: int, y: int) -> int",
        )
        result = CheckpointResult(
            symbol="add", claim=claim, verdict=Verdict.PASS,
            evidence="ok", code_hash="deadbeef" + "0" * 56,
            lane="signature", timestamp="2026-06-13T12:00:00Z", duration_ms=0.5,
        )
        doc = render_doc(sym, [(claim, result)])
        assert "deadbeef" in doc  # first 8 chars of code_hash
        assert "signature" in doc
        assert "2026-06-13T12:00:00Z" in doc
