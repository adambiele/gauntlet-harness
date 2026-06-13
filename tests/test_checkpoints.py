"""Tests for Session A2 — Checkpoint lanes.

Covers: signature (PASS/FAIL + per-component diff evidence), example (PASS/FAIL),
behavioral (PASS/FAIL), runner routing (all four claim types), span emission, and
the StubWorker fixture module integration.

Fixture module used throughout:
    def add(a: int, b: int) -> int:         # clean function; claims should PASS
    def sort_items(xs: list) -> list:       # reverses; StubWorker claims [3,1,2]==[1,2,3] → FAIL
"""

from __future__ import annotations

import pytest

from harness.checkpoints.behavioral import check_behavioral
from harness.checkpoints.example import check_example
from harness.checkpoints.runner import verify
from harness.checkpoints.signature import check_signature
from harness.contracts import (
    BehavioralClaim,
    DescriptionClaim,
    ExampleCase,
    ExampleClaim,
    SignatureClaim,
    SymbolInfo,
    Verdict,
)
from harness.observability import init_telemetry

# ---------------------------------------------------------------------------
# Fixture module source — contains both the well-behaved ``add`` and the
# deliberately-reversing ``sort_items`` (the planted-bug fixture).
# ---------------------------------------------------------------------------

MODULE_SOURCE = """\
def add(a: int, b: int) -> int:
    \"\"\"Return the sum of a and b.\"\"\"
    return a + b

def sort_items(xs: list) -> list:
    \"\"\"Return xs sorted in descending order (reversal of ascending).\"\"\"
    return sorted(xs, reverse=True)
"""

# Pre-built SymbolInfo fixtures (code_hash is arbitrary for tests — only matters
# for replay logic in persistence, not for lane correctness).
ADD_INFO = SymbolInfo(
    name="add",
    signature="(a: int, b: int) -> int",
    source="def add(a: int, b: int) -> int:\n    return a + b",
    docstring="Return the sum of a and b.",
    lineno=1,
    code_hash="deadbeef00000000",
)

SORT_INFO = SymbolInfo(
    name="sort_items",
    signature="(xs: list) -> list",
    source="def sort_items(xs: list) -> list:\n    return sorted(xs, reverse=True)",
    docstring="Return xs sorted in descending order.",
    lineno=5,
    code_hash="cafebabe00000000",
)


# ===========================================================================
# SIGNATURE LANE
# ===========================================================================

class TestSignatureLane:
    def test_pass_on_exact_match(self):
        claim = SignatureClaim(
            type="signature",
            target="add",
            prose="add takes two ints and returns int.",
            claimed_signature="(a: int, b: int) -> int",
        )
        result = check_signature(claim, ADD_INFO)
        assert result.verdict == Verdict.PASS
        assert result.lane == "signature"
        assert result.code_hash == ADD_INFO.code_hash
        assert result.duration_ms >= 0

    def test_pass_no_annotations(self):
        info = SymbolInfo(
            name="add",
            signature="(a, b)",
            source="def add(a, b): return a + b",
            docstring=None,
            lineno=1,
            code_hash="abc",
        )
        claim = SignatureClaim(
            type="signature",
            target="add",
            prose="",
            claimed_signature="(a, b)",
        )
        result = check_signature(claim, info)
        assert result.verdict == Verdict.PASS

    def test_fail_return_annotation_mismatch(self):
        # Claim says -> str, reality says -> int.
        claim = SignatureClaim(
            type="signature",
            target="add",
            prose="add returns a str.",
            claimed_signature="(a: int, b: int) -> str",
        )
        result = check_signature(claim, ADD_INFO)
        assert result.verdict == Verdict.FAIL
        assert "return annotation" in result.evidence
        assert "int" in result.evidence
        assert "str" in result.evidence

    def test_fail_param_name_mismatch(self):
        # Claim says (x, y) instead of (a, b).
        claim = SignatureClaim(
            type="signature",
            target="add",
            prose="",
            claimed_signature="(x: int, y: int) -> int",
        )
        result = check_signature(claim, ADD_INFO)
        assert result.verdict == Verdict.FAIL
        assert "param list" in result.evidence

    def test_fail_annotation_mismatch_on_param(self):
        # Claim says b: str instead of b: int.
        claim = SignatureClaim(
            type="signature",
            target="add",
            prose="",
            claimed_signature="(a: int, b: str) -> int",
        )
        result = check_signature(claim, ADD_INFO)
        assert result.verdict == Verdict.FAIL
        assert "param `b`" in result.evidence
        assert "str" in result.evidence

    def test_fail_default_mismatch_names_component(self):
        # Real: (a: int, b: int = 0) -> int  vs claim: b default = 1
        info = SymbolInfo(
            name="add",
            signature="(a: int, b: int = 0) -> int",
            source="def add(a: int, b: int = 0) -> int: return a + b",
            docstring=None,
            lineno=1,
            code_hash="abc123",
        )
        claim = SignatureClaim(
            type="signature",
            target="add",
            prose="",
            claimed_signature="(a: int, b: int = 1) -> int",
        )
        result = check_signature(claim, info)
        assert result.verdict == Verdict.FAIL
        # Evidence must name the param and both values.
        assert "param `b`" in result.evidence
        assert "0" in result.evidence
        assert "1" in result.evidence

    def test_fail_missing_return_annotation(self):
        # Real has return annotation; claim omits it.
        claim = SignatureClaim(
            type="signature",
            target="add",
            prose="",
            claimed_signature="(a: int, b: int)",
        )
        result = check_signature(claim, ADD_INFO)
        assert result.verdict == Verdict.FAIL
        assert "return annotation" in result.evidence

    def test_fail_malformed_claimed_signature(self):
        claim = SignatureClaim(
            type="signature",
            target="add",
            prose="",
            claimed_signature="(a: int, b: int->",  # broken syntax
        )
        result = check_signature(claim, ADD_INFO)
        assert result.verdict == Verdict.FAIL
        assert "could not parse claimed signature" in result.evidence

    def test_timestamp_and_lane_set(self):
        claim = SignatureClaim(
            type="signature",
            target="add",
            prose="",
            claimed_signature="(a: int, b: int) -> int",
        )
        result = check_signature(claim, ADD_INFO)
        assert result.timestamp.endswith("Z")
        assert result.lane == "signature"
        assert result.symbol == "add"


# ===========================================================================
# EXAMPLE LANE
# ===========================================================================

class TestExampleLane:
    def test_pass_single_case(self):
        claim = ExampleClaim(
            type="example",
            target="add",
            prose="add(2, 3) == 5",
            cases=[ExampleCase(args=[2, 3], kwargs={}, expected=5)],
        )
        result = check_example(claim, ADD_INFO, MODULE_SOURCE)
        assert result.verdict == Verdict.PASS
        assert result.lane == "example"

    def test_pass_multiple_cases(self):
        claim = ExampleClaim(
            type="example",
            target="add",
            prose="add works for multiple inputs",
            cases=[
                ExampleCase(args=[2, 3], kwargs={}, expected=5),
                ExampleCase(args=[0, 0], kwargs={}, expected=0),
                ExampleCase(args=[-1, 1], kwargs={}, expected=0),
            ],
        )
        result = check_example(claim, ADD_INFO, MODULE_SOURCE)
        assert result.verdict == Verdict.PASS

    def test_fail_wrong_expected(self):
        # StubWorker's planted-bug claim: sort_items([3,1,2]) claims == [1,2,3]
        # but the real function reverses → [3,2,1].
        claim = ExampleClaim(
            type="example",
            target="sort_items",
            prose="sort_items returns ascending sort",
            cases=[ExampleCase(args=[[3, 1, 2]], kwargs={}, expected=[1, 2, 3])],
        )
        result = check_example(claim, SORT_INFO, MODULE_SOURCE)
        assert result.verdict == Verdict.FAIL
        assert "expected" in result.evidence
        assert "[1, 2, 3]" in result.evidence
        assert "[3, 2, 1]" in result.evidence

    def test_fail_evidence_has_case_index(self):
        claim = ExampleClaim(
            type="example",
            target="add",
            prose="",
            cases=[
                ExampleCase(args=[1, 1], kwargs={}, expected=2),  # passes
                ExampleCase(args=[1, 1], kwargs={}, expected=99),  # fails
            ],
        )
        result = check_example(claim, ADD_INFO, MODULE_SOURCE)
        assert result.verdict == Verdict.FAIL
        assert "case 1" in result.evidence

    def test_fail_sandbox_error_in_evidence(self):
        # Module source that raises on import — sandbox error.
        bad_src = "raise RuntimeError('bad module')\ndef add(a, b): return a + b"
        claim = ExampleClaim(
            type="example",
            target="add",
            prose="",
            cases=[ExampleCase(args=[1, 2], kwargs={}, expected=3)],
        )
        result = check_example(claim, ADD_INFO, bad_src)
        assert result.verdict == Verdict.FAIL
        assert result.evidence  # some error message

    def test_fail_no_cases(self):
        claim = ExampleClaim(
            type="example",
            target="add",
            prose="",
            cases=[],
        )
        result = check_example(claim, ADD_INFO, MODULE_SOURCE)
        assert result.verdict == Verdict.FAIL

    def test_code_hash_propagated(self):
        claim = ExampleClaim(
            type="example",
            target="add",
            prose="",
            cases=[ExampleCase(args=[1, 2], kwargs={}, expected=3)],
        )
        result = check_example(claim, ADD_INFO, MODULE_SOURCE)
        assert result.code_hash == ADD_INFO.code_hash

    def test_pass_with_kwargs(self):
        # Use a module that accepts a keyword argument.
        kw_src = "def greet(name, greeting='Hello'):\n    return f'{greeting}, {name}!'\n"
        kw_info = SymbolInfo(
            name="greet",
            signature="(name, greeting='Hello')",
            source="def greet(name, greeting='Hello'): ...",
            docstring=None,
            lineno=1,
            code_hash="kwtest",
        )
        claim = ExampleClaim(
            type="example",
            target="greet",
            prose="",
            cases=[ExampleCase(args=["World"], kwargs={"greeting": "Hi"}, expected="Hi, World!")],
        )
        result = check_example(claim, kw_info, kw_src)
        assert result.verdict == Verdict.PASS


# ===========================================================================
# BEHAVIORAL LANE
# ===========================================================================

class TestBehavioralLane:
    def test_pass_self_contained_assert(self):
        claim = BehavioralClaim(
            type="behavioral",
            target="add",
            prose="add is commutative",
            asserts=["assert add(1, 2) == add(2, 1)"],
        )
        result = check_behavioral(claim, ADD_INFO, MODULE_SOURCE)
        assert result.verdict == Verdict.PASS
        assert result.lane == "behavioral"

    def test_pass_multiple_snippets(self):
        claim = BehavioralClaim(
            type="behavioral",
            target="add",
            prose="add behaves correctly",
            asserts=[
                "assert add(1, 2) == add(2, 1)",
                "assert add(0, 5) == 5",
                "assert add(-3, 3) == 0",
            ],
        )
        result = check_behavioral(claim, ADD_INFO, MODULE_SOURCE)
        assert result.verdict == Verdict.PASS

    def test_fail_assertion_error(self):
        # sort_items reverses, but this assert says it sorts ascending.
        claim = BehavioralClaim(
            type="behavioral",
            target="sort_items",
            prose="sort_items returns ascending",
            asserts=["assert sort_items([3, 1, 2]) == [1, 2, 3]"],
        )
        result = check_behavioral(claim, SORT_INFO, MODULE_SOURCE)
        assert result.verdict == Verdict.FAIL
        assert result.evidence is not None
        # Evidence should be the real traceback (AssertionError).
        assert "AssertionError" in result.evidence

    def test_fail_evidence_is_real_traceback(self):
        claim = BehavioralClaim(
            type="behavioral",
            target="add",
            prose="",
            asserts=["assert add(2, 3) == 99"],
        )
        result = check_behavioral(claim, ADD_INFO, MODULE_SOURCE)
        assert result.verdict == Verdict.FAIL
        assert "Traceback" in result.evidence
        assert "AssertionError" in result.evidence

    def test_fail_stops_at_first_failing_snippet(self):
        # Two snippets: first passes, second fails.  Fail should be reported.
        claim = BehavioralClaim(
            type="behavioral",
            target="add",
            prose="",
            asserts=[
                "assert add(1, 1) == 2",          # passes
                "assert add(1, 1) == 999",         # fails
                "assert add(1, 1) == 2",           # would pass, but short-circuit
            ],
        )
        result = check_behavioral(claim, ADD_INFO, MODULE_SOURCE)
        assert result.verdict == Verdict.FAIL

    def test_fail_no_asserts(self):
        claim = BehavioralClaim(
            type="behavioral",
            target="add",
            prose="",
            asserts=[],
        )
        result = check_behavioral(claim, ADD_INFO, MODULE_SOURCE)
        assert result.verdict == Verdict.FAIL

    def test_result_is_precomputed_none_for_multiarg(self):
        # The sandbox pre-computes result = symbol() (zero args) → None for add(a,b).
        # Snippets must NOT rely on result being populated.  Confirm it's None.
        claim = BehavioralClaim(
            type="behavioral",
            target="add",
            prose="",
            asserts=["assert result is None"],  # result = add() fails → None
        )
        result = check_behavioral(claim, ADD_INFO, MODULE_SOURCE)
        assert result.verdict == Verdict.PASS

    def test_code_hash_and_lane_set(self):
        claim = BehavioralClaim(
            type="behavioral",
            target="add",
            prose="",
            asserts=["assert add(1, 2) == 3"],
        )
        result = check_behavioral(claim, ADD_INFO, MODULE_SOURCE)
        assert result.code_hash == ADD_INFO.code_hash
        assert result.lane == "behavioral"
        assert result.symbol == "add"


# ===========================================================================
# RUNNER — routing
# ===========================================================================

class TestRunner:
    """verify() must route each claim type correctly and always return CheckpointResult."""

    def test_routes_signature_claim(self):
        claim = SignatureClaim(
            type="signature",
            target="add",
            prose="",
            claimed_signature="(a: int, b: int) -> int",
        )
        result = verify(claim, ADD_INFO, MODULE_SOURCE)
        assert result.lane == "signature"
        assert result.verdict == Verdict.PASS

    def test_routes_example_claim_pass(self):
        claim = ExampleClaim(
            type="example",
            target="add",
            prose="",
            cases=[ExampleCase(args=[10, 20], kwargs={}, expected=30)],
        )
        result = verify(claim, ADD_INFO, MODULE_SOURCE)
        assert result.lane == "example"
        assert result.verdict == Verdict.PASS

    def test_routes_example_claim_fail(self):
        # Planted-bug claim via verify() routing.
        claim = ExampleClaim(
            type="example",
            target="sort_items",
            prose="ascending sort",
            cases=[ExampleCase(args=[[3, 1, 2]], kwargs={}, expected=[1, 2, 3])],
        )
        result = verify(claim, SORT_INFO, MODULE_SOURCE)
        assert result.lane == "example"
        assert result.verdict == Verdict.FAIL

    def test_routes_behavioral_claim(self):
        claim = BehavioralClaim(
            type="behavioral",
            target="add",
            prose="",
            asserts=["assert add(5, 5) == 10"],
        )
        result = verify(claim, ADD_INFO, MODULE_SOURCE)
        assert result.lane == "behavioral"
        assert result.verdict == Verdict.PASS

    def test_routes_description_claim_to_inconclusive(self):
        claim = DescriptionClaim(
            type="description",
            target="add",
            prose="add adds two numbers together.",
        )
        result = verify(claim, ADD_INFO, MODULE_SOURCE)
        assert result.verdict == Verdict.INCONCLUSIVE
        assert result.lane == "description"
        assert "no mechanical check" in result.evidence

    def test_result_fields_always_populated(self):
        """All required CheckpointResult fields must be non-empty for every route."""
        claims = [
            SignatureClaim(type="signature", target="add", prose="", claimed_signature="(a: int, b: int) -> int"),
            ExampleClaim(type="example", target="add", prose="", cases=[ExampleCase(args=[1, 2], kwargs={}, expected=3)]),
            BehavioralClaim(type="behavioral", target="add", prose="", asserts=["assert add(1,2)==3"]),
            DescriptionClaim(type="description", target="add", prose="prose"),
        ]
        for claim in claims:
            result = verify(claim, ADD_INFO, MODULE_SOURCE)
            assert result.symbol == "add"
            assert result.lane
            assert result.verdict in (Verdict.PASS, Verdict.FAIL, Verdict.INCONCLUSIVE)
            assert result.evidence
            assert result.code_hash == ADD_INFO.code_hash
            assert result.timestamp.endswith("Z")
            assert result.duration_ms >= 0


# ===========================================================================
# RUNNER — OTel spans are emitted
# ===========================================================================

class TestRunnerSpans:
    """Confirm that verify() records spans under the expected names."""

    def setup_method(self):
        self.agg = init_telemetry("test-harness")
        self.agg.reset()

    def test_span_emitted_for_signature_lane(self):
        claim = SignatureClaim(
            type="signature",
            target="add",
            prose="",
            claimed_signature="(a: int, b: int) -> int",
        )
        verify(claim, ADD_INFO, MODULE_SOURCE)
        names = [r["name"] for r in self.agg.records]
        assert "verify.signature" in names

    def test_span_emitted_for_example_lane(self):
        claim = ExampleClaim(
            type="example",
            target="add",
            prose="",
            cases=[ExampleCase(args=[1, 2], kwargs={}, expected=3)],
        )
        verify(claim, ADD_INFO, MODULE_SOURCE)
        names = [r["name"] for r in self.agg.records]
        assert "verify.example" in names

    def test_span_emitted_for_behavioral_lane(self):
        claim = BehavioralClaim(
            type="behavioral",
            target="add",
            prose="",
            asserts=["assert add(1, 2) == 3"],
        )
        verify(claim, ADD_INFO, MODULE_SOURCE)
        names = [r["name"] for r in self.agg.records]
        assert "verify.behavioral" in names

    def test_span_emitted_for_description_lane(self):
        claim = DescriptionClaim(
            type="description",
            target="add",
            prose="some description",
        )
        verify(claim, ADD_INFO, MODULE_SOURCE)
        names = [r["name"] for r in self.agg.records]
        assert "verify.description" in names

    def test_span_has_lane_attr(self):
        claim = ExampleClaim(
            type="example",
            target="add",
            prose="",
            cases=[ExampleCase(args=[0, 0], kwargs={}, expected=0)],
        )
        verify(claim, ADD_INFO, MODULE_SOURCE)
        example_spans = [r for r in self.agg.records if r["name"] == "verify.example"]
        assert example_spans, "no verify.example span recorded"
        assert example_spans[-1]["attrs"].get("lane") == "example"

    def test_span_has_verdict_attr(self):
        claim = ExampleClaim(
            type="example",
            target="sort_items",
            prose="",
            cases=[ExampleCase(args=[[3, 1, 2]], kwargs={}, expected=[1, 2, 3])],
        )
        verify(claim, SORT_INFO, MODULE_SOURCE)
        example_spans = [r for r in self.agg.records if r["name"] == "verify.example"]
        assert example_spans, "no verify.example span recorded"
        assert example_spans[-1]["attrs"].get("verdict") == "fail"


# ===========================================================================
# INTEGRATION — StubWorker fixture claims through the runner
# ===========================================================================

class TestStubWorkerIntegration:
    """
    Run StubWorker-generated claims for ``add`` and ``sort_items`` through
    ``verify()`` to confirm the expected PASS/FAIL pattern from the spec.

    ``sort_items`` reverses; StubWorker claims [3,1,2]==[1,2,3] → example FAIL.
    ``add`` claims are correct → PASS across all lanes.
    """

    def test_add_signature_pass(self):
        claim = SignatureClaim(
            type="signature",
            target="add",
            prose="add takes two numbers and returns their sum.",
            claimed_signature=ADD_INFO.signature,
        )
        result = verify(claim, ADD_INFO, MODULE_SOURCE)
        assert result.verdict == Verdict.PASS

    def test_add_example_pass(self):
        claim = ExampleClaim(
            type="example",
            target="add",
            prose="add(2, 3) returns 5.",
            cases=[
                ExampleCase(args=[2, 3], kwargs={}, expected=5),
                ExampleCase(args=[0, 0], kwargs={}, expected=0),
            ],
        )
        result = verify(claim, ADD_INFO, MODULE_SOURCE)
        assert result.verdict == Verdict.PASS

    def test_add_behavioral_pass(self):
        claim = BehavioralClaim(
            type="behavioral",
            target="add",
            prose="add is commutative.",
            asserts=["assert add(1, 2) == add(2, 1)"],
        )
        result = verify(claim, ADD_INFO, MODULE_SOURCE)
        assert result.verdict == Verdict.PASS

    def test_sort_items_signature_passes_own_sig(self):
        # StubWorker echo's the real signature — PASS.
        claim = SignatureClaim(
            type="signature",
            target="sort_items",
            prose="sort_items takes a list and returns a list.",
            claimed_signature=SORT_INFO.signature,
        )
        result = verify(claim, SORT_INFO, MODULE_SOURCE)
        assert result.verdict == Verdict.PASS

    def test_sort_items_example_fail(self):
        # Planted-bug: StubWorker says sort_items([3,1,2]) == [1,2,3] but it reverses.
        claim = ExampleClaim(
            type="example",
            target="sort_items",
            prose="Sorting [3, 1, 2] yields [1, 2, 3].",
            cases=[ExampleCase(args=[[3, 1, 2]], kwargs={}, expected=[1, 2, 3])],
        )
        result = verify(claim, SORT_INFO, MODULE_SOURCE)
        assert result.verdict == Verdict.FAIL
        assert "[1, 2, 3]" in result.evidence  # expected
        assert "[3, 2, 1]" in result.evidence  # actual (reversed)

    def test_signature_mismatch_names_component(self):
        """Evidence must name the specific differing component, not just 'mismatch'."""
        claim = SignatureClaim(
            type="signature",
            target="add",
            prose="",
            claimed_signature="(a: int, b: int = 0) -> int",  # wrong: adds default
        )
        result = verify(claim, ADD_INFO, MODULE_SOURCE)
        assert result.verdict == Verdict.FAIL
        # Must name the param with the differing default.
        assert "param `b`" in result.evidence
