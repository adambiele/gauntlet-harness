"""Tests for A3 — Guardrails (enforce.py + rules.py).

Covers:
- Valid claim sets → no alarms, all claims returned.
- Phantom target → PHANTOM_API alarm, claim dropped.
- import statement in snippet → BEHAVIOR_CONTRADICTION alarm, claim dropped.
- Empty asserts list → claim downgraded to DescriptionClaim (no alarm).
- Snippet with zero assert statements (but non-empty list) → downgraded.
- Secret / key-like string in prose → SECRET_LEAK alarm, claim dropped.
- Absolute path in prose → SECRET_LEAK alarm, claim dropped.
- ExampleClaim with no cases → MALFORMED_CLAIM alarm, claim dropped.
- Rules module: RULES is a printable list with correct names.
- Span: enforce wraps in SPAN_GATE (observed via aggregator).
"""

from __future__ import annotations

import pytest

from harness.alarms.types import Severity
from harness.contracts import (
    BehavioralClaim,
    CodeContext,
    DescriptionClaim,
    ExampleCase,
    ExampleClaim,
    SignatureClaim,
    SymbolInfo,
)
from harness.guardrails.enforce import enforce
from harness.guardrails.rules import RULES, TARGET_EXISTS, EXAMPLE_VALID, BEHAVIORAL_SNIPPET_VETTING, SECRET_LEAK as SECRET_LEAK_RULE


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_symbol(name: str = "add") -> SymbolInfo:
    return SymbolInfo(
        name=name,
        signature="(x: int, y: int) -> int",
        source=f"def {name}(x: int, y: int) -> int:\n    return x + y",
        docstring=None,
        lineno=1,
        code_hash="abc123",
    )


def _make_ctx(*names: str) -> CodeContext:
    symbols = {name: _make_symbol(name) for name in names}
    return CodeContext(
        module_path="fake.py",
        symbols=symbols,
        module_source="def add(x, y): return x + y",
    )


def _sig(target: str = "add") -> SignatureClaim:
    return SignatureClaim(
        type="signature",
        target=target,
        prose="add takes two ints",
        claimed_signature="(x: int, y: int) -> int",
    )


def _example(target: str = "add", cases: list | None = None) -> ExampleClaim:
    if cases is None:
        cases = [ExampleCase(args=[1, 2], kwargs={}, expected=3)]
    return ExampleClaim(
        type="example",
        target=target,
        prose="add(1,2) == 3",
        cases=cases,
    )


def _behavioral(
    target: str = "add",
    asserts: list[str] | None = None,
) -> BehavioralClaim:
    if asserts is None:
        asserts = ["assert add(1, 2) == 3"]
    return BehavioralClaim(
        type="behavioral",
        target=target,
        prose="add returns sum",
        asserts=asserts,
    )


# ---------------------------------------------------------------------------
# Rules module
# ---------------------------------------------------------------------------

class TestRulesModule:
    def test_rules_list_nonempty(self):
        assert len(RULES) >= 4

    def test_rules_names(self):
        names = {r.name for r in RULES}
        assert "TARGET_EXISTS" in names
        assert "EXAMPLE_VALID" in names
        assert "BEHAVIORAL_SNIPPET_VETTING" in names
        assert "SECRET_LEAK" in names

    def test_rules_have_summary_and_detail(self):
        for rule in RULES:
            assert rule.summary, f"Rule {rule.name} missing summary"
            assert rule.detail, f"Rule {rule.name} missing detail"

    def test_behavioral_rule_mentions_security_note(self):
        # The spec requires a security model note in the behavioral rule.
        assert "NOT the security boundary" in BEHAVIORAL_SNIPPET_VETTING.detail

    def test_rules_are_printable(self):
        for rule in RULES:
            s = str(rule)
            assert rule.name in s


# ---------------------------------------------------------------------------
# Valid claim sets → no alarms
# ---------------------------------------------------------------------------

class TestValidClaims:
    def test_signature_claim_passes(self):
        ctx = _make_ctx("add")
        cleaned, alarms = enforce([_sig("add")], ctx)
        assert len(alarms) == 0
        assert len(cleaned) == 1
        assert cleaned[0].target == "add"

    def test_example_claim_passes(self):
        ctx = _make_ctx("add")
        cleaned, alarms = enforce([_example("add")], ctx)
        assert len(alarms) == 0
        assert len(cleaned) == 1

    def test_behavioral_claim_passes(self):
        ctx = _make_ctx("add")
        cleaned, alarms = enforce([_behavioral("add")], ctx)
        assert len(alarms) == 0
        assert len(cleaned) == 1
        assert isinstance(cleaned[0], BehavioralClaim)

    def test_mixed_valid_claims_pass(self):
        ctx = _make_ctx("add")
        claims = [_sig("add"), _example("add"), _behavioral("add")]
        cleaned, alarms = enforce(claims, ctx)
        assert len(alarms) == 0
        assert len(cleaned) == 3

    def test_empty_claim_list(self):
        ctx = _make_ctx("add")
        cleaned, alarms = enforce([], ctx)
        assert cleaned == []
        assert alarms == []


# ---------------------------------------------------------------------------
# Rule 1: target-exists → PHANTOM_API
# ---------------------------------------------------------------------------

class TestTargetExists:
    def test_phantom_target_raises_alarm(self):
        ctx = _make_ctx("add")
        claim = _sig("nonexistent_function")
        cleaned, alarms = enforce([claim], ctx)
        assert len(cleaned) == 0
        assert len(alarms) == 1
        assert alarms[0].type == "PHANTOM_API"
        assert alarms[0].severity == Severity.BLOCK

    def test_phantom_target_message_contains_name(self):
        ctx = _make_ctx("add")
        claim = _sig("ghost")
        _, alarms = enforce([claim], ctx)
        assert "ghost" in alarms[0].message

    def test_phantom_target_drops_claim(self):
        ctx = _make_ctx("add")
        # Mix a valid claim with a phantom one
        cleaned, alarms = enforce([_sig("add"), _sig("ghost")], ctx)
        assert len(cleaned) == 1
        assert cleaned[0].target == "add"
        assert len(alarms) == 1
        assert alarms[0].type == "PHANTOM_API"

    def test_empty_ctx_symbols(self):
        ctx = CodeContext(module_path="x.py", symbols={}, module_source="")
        cleaned, alarms = enforce([_sig("add")], ctx)
        assert len(cleaned) == 0
        assert alarms[0].type == "PHANTOM_API"

    def test_phantom_alarm_has_recommended_action(self):
        ctx = _make_ctx("add")
        _, alarms = enforce([_sig("missing")], ctx)
        assert alarms[0].recommended_action  # non-empty
        assert "drop" in alarms[0].recommended_action.lower()


# ---------------------------------------------------------------------------
# Rule 3: behavioral snippet vetting
# ---------------------------------------------------------------------------

class TestBehavioralSnippetVetting:
    def test_import_os_rejected(self):
        ctx = _make_ctx("add")
        claim = _behavioral("add", asserts=["import os\nassert add(1,2) == 3"])
        cleaned, alarms = enforce([claim], ctx)
        assert len(cleaned) == 0
        assert len(alarms) == 1
        assert alarms[0].type == "BEHAVIOR_CONTRADICTION"
        assert alarms[0].severity == Severity.BLOCK

    def test_from_import_rejected(self):
        ctx = _make_ctx("add")
        claim = _behavioral("add", asserts=["from os import path\nassert add(1,2)==3"])
        cleaned, alarms = enforce([claim], ctx)
        assert len(cleaned) == 0
        assert alarms[0].type == "BEHAVIOR_CONTRADICTION"

    def test_eval_call_rejected(self):
        ctx = _make_ctx("add")
        claim = _behavioral("add", asserts=["assert eval('add(1,2)') == 3"])
        cleaned, alarms = enforce([claim], ctx)
        assert len(cleaned) == 0
        assert alarms[0].type == "BEHAVIOR_CONTRADICTION"

    def test_exec_call_rejected(self):
        ctx = _make_ctx("add")
        claim = _behavioral("add", asserts=["exec('x=1')\nassert add(1,2)==3"])
        cleaned, alarms = enforce([claim], ctx)
        assert len(cleaned) == 0
        assert alarms[0].type == "BEHAVIOR_CONTRADICTION"

    def test_open_call_rejected(self):
        ctx = _make_ctx("add")
        # Use a relative-path arg so only the AST check (not SECRET_LEAK) fires.
        claim = _behavioral("add", asserts=["open('config.txt')\nassert add(1,2)==3"])
        cleaned, alarms = enforce([claim], ctx)
        assert len(cleaned) == 0
        assert alarms[0].type == "BEHAVIOR_CONTRADICTION"

    def test_dunder_attr_access_rejected(self):
        ctx = _make_ctx("add")
        claim = _behavioral("add", asserts=["assert add.__class__.__name__ == 'function'"])
        cleaned, alarms = enforce([claim], ctx)
        assert len(cleaned) == 0
        assert alarms[0].type == "BEHAVIOR_CONTRADICTION"

    def test_snippet_must_reference_target(self):
        ctx = _make_ctx("add")
        # Snippet doesn't call `add` at all
        claim = _behavioral("add", asserts=["assert 1 + 1 == 2"])
        cleaned, alarms = enforce([claim], ctx)
        assert len(cleaned) == 0
        assert alarms[0].type == "BEHAVIOR_CONTRADICTION"

    def test_snippet_references_target_passes(self):
        ctx = _make_ctx("add")
        claim = _behavioral("add", asserts=["assert add(0, 0) == 0"])
        cleaned, alarms = enforce([claim], ctx)
        assert len(alarms) == 0
        assert len(cleaned) == 1

    def test_no_asserts_downgraded_to_description(self):
        """BehavioralClaim with snippets but no assert → downgraded, no alarm."""
        ctx = _make_ctx("add")
        # Snippet references target but has no assert keyword
        claim = _behavioral("add", asserts=["result = add(1, 2)"])
        cleaned, alarms = enforce([claim], ctx)
        # No alarms — downgrade is silent
        assert len(alarms) == 0
        # Claim is downgraded to DescriptionClaim
        assert len(cleaned) == 1
        assert isinstance(cleaned[0], DescriptionClaim)
        assert cleaned[0].target == "add"

    def test_empty_asserts_list_downgraded(self):
        """BehavioralClaim with asserts=[] → downgraded to DescriptionClaim."""
        ctx = _make_ctx("add")
        claim = BehavioralClaim(
            type="behavioral",
            target="add",
            prose="add exists",
            asserts=[],
        )
        cleaned, alarms = enforce([claim], ctx)
        assert len(alarms) == 0
        assert len(cleaned) == 1
        assert isinstance(cleaned[0], DescriptionClaim)

    def test_alarm_has_behavior_contradiction_action(self):
        ctx = _make_ctx("add")
        claim = _behavioral("add", asserts=["import sys\nassert add(1,2)==3"])
        _, alarms = enforce([claim], ctx)
        assert alarms[0].type == "BEHAVIOR_CONTRADICTION"
        assert alarms[0].recommended_action  # non-empty from registry


# ---------------------------------------------------------------------------
# Rule 2: example valid
# ---------------------------------------------------------------------------

class TestExampleValid:
    def test_no_cases_raises_malformed(self):
        ctx = _make_ctx("add")
        claim = _example("add", cases=[])
        cleaned, alarms = enforce([claim], ctx)
        assert len(cleaned) == 0
        assert len(alarms) == 1
        assert alarms[0].type == "MALFORMED_CLAIM"

    def test_valid_example_passes(self):
        ctx = _make_ctx("add")
        claim = _example("add")
        cleaned, alarms = enforce([claim], ctx)
        assert len(alarms) == 0
        assert len(cleaned) == 1

    def test_multiple_cases_pass(self):
        ctx = _make_ctx("add")
        claim = _example("add", cases=[
            ExampleCase(args=[1, 2], kwargs={}, expected=3),
            ExampleCase(args=[0, 0], kwargs={}, expected=0),
        ])
        cleaned, alarms = enforce([claim], ctx)
        assert len(alarms) == 0
        assert len(cleaned) == 1


# ---------------------------------------------------------------------------
# Rule 4 (applied early): SECRET_LEAK
# ---------------------------------------------------------------------------

class TestSecretLeak:
    def test_long_hex_string_in_prose_triggers_alarm(self):
        ctx = _make_ctx("add")
        # 32+ hex chars looks like an API key / hash
        claim = SignatureClaim(
            type="signature",
            target="add",
            prose="use key deadbeefdeadbeefdeadbeefdeadbeef for auth",
            claimed_signature="(x: int, y: int) -> int",
        )
        cleaned, alarms = enforce([claim], ctx)
        assert len(cleaned) == 0
        assert alarms[0].type == "SECRET_LEAK"
        assert alarms[0].severity == Severity.BLOCK

    def test_key_prefix_pattern_triggers_alarm(self):
        ctx = _make_ctx("add")
        claim = SignatureClaim(
            type="signature",
            target="add",
            prose="set secret=mysupersecretpassword123 to authenticate",
            claimed_signature="(x: int, y: int) -> int",
        )
        cleaned, alarms = enforce([claim], ctx)
        assert len(cleaned) == 0
        assert alarms[0].type == "SECRET_LEAK"

    def test_absolute_unix_path_triggers_alarm(self):
        ctx = _make_ctx("add")
        claim = SignatureClaim(
            type="signature",
            target="add",
            prose="reads from /home/user/secret_config/keys.json file",
            claimed_signature="(x: int, y: int) -> int",
        )
        cleaned, alarms = enforce([claim], ctx)
        assert len(cleaned) == 0
        assert alarms[0].type == "SECRET_LEAK"

    def test_absolute_path_in_snippet_triggers_alarm(self):
        ctx = _make_ctx("add")
        # Absolute path inside a behavioral snippet
        claim = _behavioral("add", asserts=["assert add(1, 2) == 3  # /etc/passwd"])
        cleaned, alarms = enforce([claim], ctx)
        # Absolute path is long enough to trigger
        assert len(cleaned) == 0
        assert any(a.type == "SECRET_LEAK" for a in alarms)

    def test_secret_alarm_drops_claim(self):
        ctx = _make_ctx("add")
        good = _sig("add")
        bad = SignatureClaim(
            type="signature",
            target="add",
            prose="token=sk-abcdefghijklmnopqrstuvwxyz12345678",
            claimed_signature="(x: int, y: int) -> int",
        )
        cleaned, alarms = enforce([good, bad], ctx)
        # Good claim passes, bad claim is dropped
        assert len(cleaned) == 1
        assert cleaned[0] is good
        assert alarms[0].type == "SECRET_LEAK"

    def test_clean_prose_not_flagged(self):
        ctx = _make_ctx("add")
        claim = SignatureClaim(
            type="signature",
            target="add",
            prose="Takes two integers and returns their sum.",
            claimed_signature="(x: int, y: int) -> int",
        )
        cleaned, alarms = enforce([claim], ctx)
        assert len(alarms) == 0
        assert len(cleaned) == 1


# ---------------------------------------------------------------------------
# Alarm structure
# ---------------------------------------------------------------------------

class TestAlarmStructure:
    def test_alarm_copies_severity_from_registry(self):
        ctx = _make_ctx("add")
        _, alarms = enforce([_sig("missing")], ctx)
        alarm = alarms[0]
        assert alarm.severity == Severity.BLOCK  # PHANTOM_API is BLOCK
        assert alarm.recommended_action  # non-empty

    def test_alarm_has_timestamp(self):
        ctx = _make_ctx("add")
        _, alarms = enforce([_sig("missing")], ctx)
        alarm = alarms[0]
        assert alarm.timestamp  # non-empty ISO string
        # Should be a valid ISO timestamp
        from datetime import datetime
        datetime.fromisoformat(alarm.timestamp)

    def test_alarm_has_symbol(self):
        ctx = _make_ctx("add")
        _, alarms = enforce([_sig("missing")], ctx)
        assert alarms[0].symbol == "missing"

    def test_alarm_has_claim_ref(self):
        ctx = _make_ctx("add")
        _, alarms = enforce([_sig("missing")], ctx)
        assert alarms[0].claim_ref is not None


# ---------------------------------------------------------------------------
# OTel span wrapping
# ---------------------------------------------------------------------------

class TestSpanWrapping:
    def test_enforce_emits_gate_span(self):
        from harness.observability import SPAN_GATE, init_telemetry

        agg = init_telemetry("test-guardrails")
        agg.reset()

        ctx = _make_ctx("add")
        enforce([_sig("add")], ctx)

        gate_records = agg.by_name(SPAN_GATE)
        assert len(gate_records) >= 1


# ---------------------------------------------------------------------------
# Edge cases / combinations
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_description_claim_passes_with_no_checks(self):
        ctx = _make_ctx("add")
        claim = DescriptionClaim(type="description", target="add", prose="Some description.")
        cleaned, alarms = enforce([claim], ctx)
        assert len(alarms) == 0
        assert len(cleaned) == 1

    def test_multiple_alarms_for_multiple_bad_claims(self):
        ctx = _make_ctx("add")
        claims = [
            _sig("ghost1"),
            _sig("ghost2"),
        ]
        cleaned, alarms = enforce(claims, ctx)
        assert len(cleaned) == 0
        assert len(alarms) == 2
        assert all(a.type == "PHANTOM_API" for a in alarms)

    def test_behavioral_with_multiple_snippets_all_must_pass(self):
        """If any snippet fails vetting, the whole claim is dropped."""
        ctx = _make_ctx("add")
        claim = BehavioralClaim(
            type="behavioral",
            target="add",
            prose="tests add",
            asserts=[
                "assert add(1, 2) == 3",  # clean
                "import os\nassert add(1,2)==3",  # bad
            ],
        )
        cleaned, alarms = enforce([claim], ctx)
        assert len(cleaned) == 0
        assert alarms[0].type == "BEHAVIOR_CONTRADICTION"

    def test_order_preserved_in_cleaned(self):
        ctx = _make_ctx("add", "multiply")
        s1 = _sig("add")
        s2 = _sig("multiply")
        cleaned, alarms = enforce([s1, s2], ctx)
        assert len(alarms) == 0
        assert cleaned[0] is s1
        assert cleaned[1] is s2

    def test_phantom_checked_before_secret(self):
        """Phantom target → only PHANTOM_API alarm, no SECRET_LEAK for same claim."""
        ctx = _make_ctx("add")
        claim = SignatureClaim(
            type="signature",
            target="nonexistent",
            prose="token=sk-abcdefghijklmnopqrstuvwxyz12345678",
            claimed_signature="(x) -> int",
        )
        _, alarms = enforce([claim], ctx)
        # Should see PHANTOM_API (checked first) and claim is immediately dropped
        assert alarms[0].type == "PHANTOM_API"
        # Once claim is dropped via PHANTOM_API, no further checks run
        assert len(alarms) == 1
