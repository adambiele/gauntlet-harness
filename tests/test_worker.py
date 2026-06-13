"""Tests for A5 — Worker transports (llm_worker.py + prompts.py).

Tests use a fake ``_complete`` (subclass override) — no live API calls, no anthropic/openai
SDK required. Covers:
- Module imports without anthropic/openai installed.
- BaseLLMWorker with a valid response → validated Claim list.
- BaseLLMWorker with malformed model output → ClaimParseError re-raised.
- Hybrid feedback prompt construction (latest = full detail; earlier = one-liners).
- make_worker factory: correct transport for each name.
- ClaudeWorker / LocalWorker can be instantiated and have correct attributes.
- prompts.py seam has SYSTEM_PROMPT with the behavioral self-containment instruction.
"""

from __future__ import annotations

import json
from typing import Optional

import pytest

from harness.alarms.types import Alarm, Severity
from harness.contracts import (
    BehavioralClaim,
    ClaimParseError,
    ExampleCase,
    ExampleClaim,
    SignatureClaim,
    SymbolInfo,
)
from harness.worker.base import StubWorker
from harness.worker.llm_worker import BaseLLMWorker, ClaudeWorker, LocalWorker, make_worker
from harness.worker.prompts import SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _symbol(
    name: str = "add",
    signature: str = "(x: int, y: int) -> int",
    source: str = "def add(x: int, y: int) -> int:\n    return x + y",
    docstring: Optional[str] = "Return x + y.",
) -> SymbolInfo:
    return SymbolInfo(
        name=name,
        signature=signature,
        source=source,
        docstring=docstring,
        lineno=1,
        code_hash="abc123",
    )


def _alarm(
    alarm_type: str = "EXAMPLE_FAILED",
    message: str = "expected 5, got 3",
    symbol: str = "add",
) -> Alarm:
    return Alarm(
        type=alarm_type,
        severity=Severity.HIGH,
        symbol=symbol,
        claim_ref=None,
        message=message,
        recommended_action="regenerate; feed actual traceback",
        timestamp="2026-06-13T00:00:00Z",
    )


# A fake BaseLLMWorker that short-circuits _complete for testing.
class FakeWorker(BaseLLMWorker):
    """BaseLLMWorker subclass with a controllable _complete response."""

    def __init__(self, response: str, model: str = "fake-model") -> None:
        self.model = model
        self._response = response
        self._calls: list[tuple[str, str]] = []

    def _complete(self, system: str, user: str) -> str:
        self._calls.append((system, user))
        return self._response


# ---------------------------------------------------------------------------
# Module-level import smoke test
# ---------------------------------------------------------------------------

def test_llm_worker_imports_without_sdks():
    """The module must be importable even if anthropic/openai are not installed."""
    # If we reach here the import succeeded (the top of this file already imports it).
    import harness.worker.llm_worker as m  # noqa: F401
    assert hasattr(m, "BaseLLMWorker")
    assert hasattr(m, "ClaudeWorker")
    assert hasattr(m, "LocalWorker")
    assert hasattr(m, "make_worker")


# ---------------------------------------------------------------------------
# FakeWorker — valid response
# ---------------------------------------------------------------------------

_VALID_CLAIMS_JSON = json.dumps([
    {
        "type": "signature",
        "target": "add",
        "prose": "add takes two ints and returns their sum.",
        "claimed_signature": "(x: int, y: int) -> int",
    },
    {
        "type": "example",
        "target": "add",
        "prose": "add(2, 3) returns 5.",
        "cases": [{"args": [2, 3], "kwargs": {}, "expected": 5}],
    },
    {
        "type": "behavioral",
        "target": "add",
        "prose": "add is commutative.",
        "asserts": ["assert add(1, 2) == add(2, 1)"],
    },
])


def test_fake_worker_returns_validated_claims():
    """A FakeWorker with valid JSON returns a list of typed Claim objects."""
    worker = FakeWorker(_VALID_CLAIMS_JSON)
    claims = worker.generate(_symbol())
    assert len(claims) == 3
    types = {c.type for c in claims}
    assert types == {"signature", "example", "behavioral"}


def test_fake_worker_signature_claim_fields():
    worker = FakeWorker(_VALID_CLAIMS_JSON)
    claims = worker.generate(_symbol())
    sig = next(c for c in claims if c.type == "signature")
    assert isinstance(sig, SignatureClaim)
    assert sig.target == "add"
    assert sig.claimed_signature == "(x: int, y: int) -> int"


def test_fake_worker_example_claim_fields():
    worker = FakeWorker(_VALID_CLAIMS_JSON)
    claims = worker.generate(_symbol())
    ex = next(c for c in claims if c.type == "example")
    assert isinstance(ex, ExampleClaim)
    assert len(ex.cases) == 1
    assert ex.cases[0].args == [2, 3]
    assert ex.cases[0].expected == 5


def test_fake_worker_behavioral_claim_fields():
    worker = FakeWorker(_VALID_CLAIMS_JSON)
    claims = worker.generate(_symbol())
    beh = next(c for c in claims if c.type == "behavioral")
    assert isinstance(beh, BehavioralClaim)
    assert len(beh.asserts) == 1
    assert "add(1, 2)" in beh.asserts[0]


# ---------------------------------------------------------------------------
# FakeWorker — malformed output → ClaimParseError
# ---------------------------------------------------------------------------

def test_malformed_json_raises_claim_parse_error():
    """Non-JSON response from the model → ClaimParseError, not a crash."""
    worker = FakeWorker("this is not JSON at all")
    with pytest.raises(ClaimParseError):
        worker.generate(_symbol())


def test_wrong_type_discriminator_raises_claim_parse_error():
    """Unknown 'type' value → ClaimParseError."""
    bad = json.dumps([{"type": "unknown_type", "target": "add", "prose": "x"}])
    worker = FakeWorker(bad)
    with pytest.raises(ClaimParseError):
        worker.generate(_symbol())


def test_missing_required_field_raises_claim_parse_error():
    """Missing required field (claimed_signature on signature claim) → ClaimParseError."""
    bad = json.dumps([{"type": "signature", "target": "add", "prose": "x"}])
    worker = FakeWorker(bad)
    with pytest.raises(ClaimParseError):
        worker.generate(_symbol())


def test_not_a_list_raises_claim_parse_error():
    """Model returns a dict instead of a list → ClaimParseError."""
    bad = json.dumps({"type": "signature", "target": "add", "prose": "x",
                      "claimed_signature": "()"})
    worker = FakeWorker(bad)
    with pytest.raises(ClaimParseError):
        worker.generate(_symbol())


def test_empty_list_is_valid():
    """An empty JSON list is technically valid (no claims — the loop handles it)."""
    worker = FakeWorker("[]")
    claims = worker.generate(_symbol())
    assert claims == []


# ---------------------------------------------------------------------------
# Hybrid feedback prompt construction
# ---------------------------------------------------------------------------

def test_generate_called_with_system_prompt():
    """The system prompt constant from prompts.py is passed to _complete."""
    worker = FakeWorker(_VALID_CLAIMS_JSON)
    worker.generate(_symbol())
    assert len(worker._calls) == 1
    system, _user = worker._calls[0]
    assert system == SYSTEM_PROMPT


def test_user_prompt_contains_symbol_name():
    worker = FakeWorker(_VALID_CLAIMS_JSON)
    worker.generate(_symbol("my_func"))
    _system, user = worker._calls[0]
    assert "my_func" in user


def test_user_prompt_contains_signature():
    worker = FakeWorker(_VALID_CLAIMS_JSON)
    worker.generate(_symbol(signature="(a: str, b: int) -> bool"))
    _system, user = worker._calls[0]
    assert "(a: str, b: int) -> bool" in user


def test_user_prompt_contains_source():
    worker = FakeWorker(_VALID_CLAIMS_JSON)
    sym = _symbol(source="def add(x, y):\n    return x + y")
    worker.generate(sym)
    _system, user = worker._calls[0]
    assert "def add(x, y):" in user


def test_user_prompt_contains_docstring_when_present():
    worker = FakeWorker(_VALID_CLAIMS_JSON)
    worker.generate(_symbol(docstring="Adds two numbers."))
    _system, user = worker._calls[0]
    assert "Adds two numbers." in user


def test_no_feedback_prompt_has_no_feedback_section():
    worker = FakeWorker(_VALID_CLAIMS_JSON)
    worker.generate(_symbol(), feedback=None)
    _system, user = worker._calls[0]
    assert "Previous attempt feedback" not in user


def test_single_feedback_alarm_appears_with_full_detail():
    """One alarm → full detail (message + recommended action)."""
    worker = FakeWorker(_VALID_CLAIMS_JSON)
    alarm = _alarm(message="expected 5, got 3")
    worker.generate(_symbol(), feedback=[alarm])
    _system, user = worker._calls[0]
    assert "Previous attempt feedback" in user
    assert "expected 5, got 3" in user
    assert "latest" in user


def test_multiple_feedback_alarms_hybrid_format():
    """Multiple alarms → one-liners for earlier, full detail for the last."""
    worker = FakeWorker(_VALID_CLAIMS_JSON)
    alarms = [
        _alarm(alarm_type="EXAMPLE_FAILED", message="first failure"),
        _alarm(alarm_type="EXAMPLE_FAILED", message="second failure"),
        _alarm(alarm_type="BEHAVIOR_CONTRADICTION", message="third failure, this is latest"),
    ]
    worker.generate(_symbol(), feedback=alarms)
    _system, user = worker._calls[0]

    # Earlier alarms: collapsed to one-liners (attempt N format)
    assert "attempt 1" in user
    assert "first failure" in user
    assert "attempt 2" in user
    assert "second failure" in user

    # Latest: full detail
    assert "latest" in user
    assert "third failure, this is latest" in user


def test_feedback_does_not_appear_when_list_empty():
    """Empty feedback list → treated same as None, no feedback section."""
    worker = FakeWorker(_VALID_CLAIMS_JSON)
    worker.generate(_symbol(), feedback=[])
    _system, user = worker._calls[0]
    assert "Previous attempt feedback" not in user


# ---------------------------------------------------------------------------
# make_worker factory
# ---------------------------------------------------------------------------

def test_make_worker_stub():
    w = make_worker("stub")
    assert isinstance(w, StubWorker)


def test_make_worker_opus():
    w = make_worker("opus")
    assert isinstance(w, ClaudeWorker)
    assert w.model == "claude-opus-4-8"


def test_make_worker_claude_alias():
    w = make_worker("claude")
    assert isinstance(w, ClaudeWorker)
    assert w.model == "claude-opus-4-8"


def test_make_worker_haiku():
    w = make_worker("haiku")
    assert isinstance(w, ClaudeWorker)
    assert w.model == "claude-haiku-4-5"


def test_make_worker_qwen():
    w = make_worker("qwen")
    assert isinstance(w, LocalWorker)
    assert w.model == "qwen3-coder"


def test_make_worker_local_alias():
    w = make_worker("local")
    assert isinstance(w, LocalWorker)
    assert w.model == "qwen3-coder"


def test_make_worker_unknown_raises():
    with pytest.raises(ValueError, match="Unknown worker name"):
        make_worker("gpt4")


def test_make_worker_case_insensitive():
    """Factory should handle mixed case (strip + lower)."""
    w = make_worker("  Opus  ")
    assert isinstance(w, ClaudeWorker)


# ---------------------------------------------------------------------------
# ClaudeWorker / LocalWorker attributes (instantiation only — no SDK calls)
# ---------------------------------------------------------------------------

def test_claude_worker_default_model():
    w = ClaudeWorker()
    assert w.model == "claude-opus-4-8"


def test_claude_worker_custom_model():
    w = ClaudeWorker(model="claude-haiku-4-5")
    assert w.model == "claude-haiku-4-5"


def test_local_worker_default_attributes():
    w = LocalWorker()
    assert w.model == "qwen3-coder"
    assert w._base_url == "http://10.10.2.113:4000/v1"


def test_local_worker_custom_base_url():
    w = LocalWorker(base_url="http://localhost:8000/v1")
    assert w._base_url == "http://localhost:8000/v1"


# ---------------------------------------------------------------------------
# prompts.py seam
# ---------------------------------------------------------------------------

def test_system_prompt_is_a_string():
    assert isinstance(SYSTEM_PROMPT, str)
    assert len(SYSTEM_PROMPT) > 100  # non-trivial content


def test_system_prompt_contains_behavioral_self_containment_instruction():
    """The S0 note: behavioral asserts must be self-contained with explicit inputs."""
    assert "self-contain" in SYSTEM_PROMPT.lower() or "explicit" in SYSTEM_PROMPT.lower()
    # Specifically, the hint about 'result' being None for multi-arg functions.
    assert "None" in SYSTEM_PROMPT or "explicit" in SYSTEM_PROMPT


def test_system_prompt_mentions_json_array():
    """The model must know to emit a JSON array."""
    prompt_lower = SYSTEM_PROMPT.lower()
    assert "json" in prompt_lower
    assert "array" in prompt_lower or "list" in prompt_lower


def test_system_prompt_mentions_claim_types():
    """All four claim types should be mentioned."""
    for claim_type in ("signature", "example", "behavioral", "description"):
        assert claim_type in SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Span wrapping — verify SPAN_GENERATE is recorded by the aggregator
# ---------------------------------------------------------------------------

def test_generate_records_span():
    """generate() wraps the call in a SPAN_GENERATE span visible to the aggregator."""
    from harness.observability import SPAN_GENERATE, get_aggregator, init_telemetry

    agg = init_telemetry("harness-test-worker")
    agg.reset()

    worker = FakeWorker(_VALID_CLAIMS_JSON, model="fake-model")
    worker.generate(_symbol())

    records = agg.by_name(SPAN_GENERATE)
    assert len(records) >= 1
    assert records[-1]["attrs"].get("model") == "fake-model"
