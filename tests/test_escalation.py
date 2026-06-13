"""Tests for harness.escalation (Session A7).

Coverage:
- EscalationHandler: ABC cannot be instantiated directly.
- BatchHandler.handle: appends to escalations.jsonl, accumulates in memory.
- BatchHandler.triage_list: returns all accumulated records; returns a copy (isolation).
- to_event: converts a record to a ClaimEscalated SSE event.
- Claim summary helper: truncation, type prefix, missing prose.
- Integration: full handle → triage_list → to_event pipeline.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from harness.adapters.events import ClaimEscalated, parse_event
from harness.contracts import (
    BehavioralClaim,
    DescriptionClaim,
    ExampleCase,
    ExampleClaim,
    SignatureClaim,
)
from harness.escalation import BatchHandler, EscalationHandler
from harness.escalation.handlers import _claim_summary, to_event
from harness.persistence.store import LocalFileStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _store_and_run() -> tuple[LocalFileStore, str, Path]:
    """Create a temp-dir LocalFileStore and a fresh run; return (store, run_id, run_dir)."""
    tmp = tempfile.mkdtemp()
    store = LocalFileStore(root=tmp)
    run_id = store.new_run({"module": "test_module", "model": "stub"})
    run_dir = Path(tmp) / run_id
    return store, run_id, run_dir


def _description_claim(target: str = "my_func", prose: str = "Does something.") -> DescriptionClaim:
    return DescriptionClaim(type="description", target=target, prose=prose)


def _signature_claim(target: str = "add") -> SignatureClaim:
    return SignatureClaim(
        type="signature",
        target=target,
        prose="add takes two ints and returns an int",
        claimed_signature="(x: int, y: int) -> int",
    )


def _example_claim(target: str = "add") -> ExampleClaim:
    return ExampleClaim(
        type="example",
        target=target,
        prose="add(1, 2) returns 3",
        cases=[ExampleCase(args=[1, 2], kwargs={}, expected=3)],
    )


def _behavioral_claim(target: str = "add") -> BehavioralClaim:
    return BehavioralClaim(
        type="behavioral",
        target=target,
        prose="add is commutative",
        asserts=["assert add(1, 2) == add(2, 1)"],
    )


# ---------------------------------------------------------------------------
# EscalationHandler ABC
# ---------------------------------------------------------------------------


class TestEscalationHandlerABC:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            EscalationHandler()  # type: ignore[abstract]

    def test_batch_handler_is_subclass(self):
        assert issubclass(BatchHandler, EscalationHandler)

    def test_batch_handler_is_concrete(self):
        """BatchHandler can be instantiated — it implements all abstract methods."""
        handler = BatchHandler()
        assert isinstance(handler, EscalationHandler)


# ---------------------------------------------------------------------------
# _claim_summary helper
# ---------------------------------------------------------------------------


class TestClaimSummary:
    def test_description_claim(self):
        claim = _description_claim(prose="Does something useful.")
        summary = _claim_summary(claim)
        assert "[description]" in summary
        assert "Does something useful." in summary

    def test_signature_claim(self):
        claim = _signature_claim()
        summary = _claim_summary(claim)
        assert "[signature]" in summary

    def test_example_claim(self):
        claim = _example_claim()
        summary = _claim_summary(claim)
        assert "[example]" in summary

    def test_behavioral_claim(self):
        claim = _behavioral_claim()
        summary = _claim_summary(claim)
        assert "[behavioral]" in summary

    def test_prose_included(self):
        claim = _description_claim(prose="Very important description.")
        summary = _claim_summary(claim)
        assert "Very important description." in summary

    def test_long_prose_truncated(self):
        long_prose = "x" * 200
        claim = _description_claim(prose=long_prose)
        summary = _claim_summary(claim)
        # Must be shorter than the full prose + type prefix overhead.
        assert len(summary) < len(long_prose) + 20
        assert summary.endswith("...")

    def test_truncation_boundary_is_120_chars(self):
        # Prose of exactly 120 chars should NOT be truncated.
        prose_120 = "a" * 120
        claim = _description_claim(prose=prose_120)
        summary = _claim_summary(claim)
        assert not summary.endswith("...")
        # Prose of 121 chars should be.
        prose_121 = "a" * 121
        claim2 = _description_claim(prose=prose_121)
        summary2 = _claim_summary(claim2)
        assert summary2.endswith("...")

    def test_empty_prose_returns_type_only(self):
        claim = DescriptionClaim(type="description", target="f", prose="")
        summary = _claim_summary(claim)
        assert summary == "[description]"


# ---------------------------------------------------------------------------
# BatchHandler.handle — persistence
# ---------------------------------------------------------------------------


class TestBatchHandlerHandle:
    def test_creates_escalations_jsonl(self):
        store, run_id, run_dir = _store_and_run()
        handler = BatchHandler()
        handler.handle(run_id, "add", _description_claim(), "INCONCLUSIVE", store)
        assert (run_dir / "escalations.jsonl").exists()

    def test_one_line_per_handle(self):
        store, run_id, run_dir = _store_and_run()
        handler = BatchHandler()
        handler.handle(run_id, "add", _description_claim(), "INCONCLUSIVE", store)
        handler.handle(run_id, "sort_items", _example_claim("sort_items"), "retry exhausted", store)
        lines = (run_dir / "escalations.jsonl").read_text().splitlines()
        assert len(lines) == 2

    def test_jsonl_line_is_valid_json(self):
        store, run_id, run_dir = _store_and_run()
        handler = BatchHandler()
        handler.handle(run_id, "add", _description_claim(), "INCONCLUSIVE", store)
        line = (run_dir / "escalations.jsonl").read_text().strip()
        record = json.loads(line)
        assert isinstance(record, dict)

    def test_jsonl_record_has_required_fields(self):
        store, run_id, run_dir = _store_and_run()
        handler = BatchHandler()
        handler.handle(run_id, "my_fn", _description_claim("my_fn", "A function."), "INCONCLUSIVE", store)
        record = json.loads((run_dir / "escalations.jsonl").read_text().strip())
        assert record["symbol"] == "my_fn"
        assert "claim_summary" in record
        assert record["reason"] == "INCONCLUSIVE"
        assert "timestamp" in record

    def test_claim_summary_in_record(self):
        store, run_id, run_dir = _store_and_run()
        handler = BatchHandler()
        claim = _description_claim(prose="Does something.")
        handler.handle(run_id, "add", claim, "INCONCLUSIVE", store)
        record = json.loads((run_dir / "escalations.jsonl").read_text().strip())
        assert "[description]" in record["claim_summary"]

    def test_timestamp_is_iso_utc(self):
        store, run_id, run_dir = _store_and_run()
        handler = BatchHandler()
        handler.handle(run_id, "add", _description_claim(), "INCONCLUSIVE", store)
        record = json.loads((run_dir / "escalations.jsonl").read_text().strip())
        from datetime import datetime
        dt = datetime.fromisoformat(record["timestamp"])
        assert dt.tzinfo is not None

    def test_different_claim_types_all_persist(self):
        store, run_id, run_dir = _store_and_run()
        handler = BatchHandler()
        claims = [
            ("sig_fn", _signature_claim("sig_fn"), "INCONCLUSIVE"),
            ("ex_fn", _example_claim("ex_fn"), "retry exhausted"),
            ("beh_fn", _behavioral_claim("beh_fn"), "INCONCLUSIVE"),
            ("desc_fn", _description_claim("desc_fn"), "INCONCLUSIVE"),
        ]
        for sym, claim, reason in claims:
            handler.handle(run_id, sym, claim, reason, store)
        lines = (run_dir / "escalations.jsonl").read_text().splitlines()
        assert len(lines) == 4

    def test_returns_none(self):
        """handle() has no return value contract — must be None."""
        store, run_id, _ = _store_and_run()
        handler = BatchHandler()
        result = handler.handle(run_id, "add", _description_claim(), "INCONCLUSIVE", store)
        assert result is None


# ---------------------------------------------------------------------------
# BatchHandler — in-memory accumulation
# ---------------------------------------------------------------------------


class TestBatchHandlerMemory:
    def test_triage_list_empty_initially(self):
        handler = BatchHandler()
        assert handler.triage_list() == []

    def test_triage_list_has_one_entry_after_one_handle(self):
        store, run_id, _ = _store_and_run()
        handler = BatchHandler()
        handler.handle(run_id, "add", _description_claim(), "INCONCLUSIVE", store)
        assert len(handler.triage_list()) == 1

    def test_triage_list_accumulates_multiple_entries(self):
        store, run_id, _ = _store_and_run()
        handler = BatchHandler()
        for i in range(5):
            handler.handle(run_id, f"fn_{i}", _description_claim(), "INCONCLUSIVE", store)
        assert len(handler.triage_list()) == 5

    def test_triage_list_entries_have_correct_fields(self):
        store, run_id, _ = _store_and_run()
        handler = BatchHandler()
        handler.handle(run_id, "my_func", _description_claim("my_func", "Does X."), "retry exhausted", store)
        items = handler.triage_list()
        assert len(items) == 1
        item = items[0]
        assert item["symbol"] == "my_func"
        assert item["reason"] == "retry exhausted"
        assert "claim_summary" in item
        assert "timestamp" in item

    def test_triage_list_returns_copy(self):
        """Mutating the returned list must not affect the handler's internal state."""
        store, run_id, _ = _store_and_run()
        handler = BatchHandler()
        handler.handle(run_id, "add", _description_claim(), "INCONCLUSIVE", store)
        copy1 = handler.triage_list()
        copy1.append({"injected": True})
        copy2 = handler.triage_list()
        assert len(copy2) == 1, "internal list was modified through the returned copy"

    def test_triage_list_preserves_insertion_order(self):
        store, run_id, _ = _store_and_run()
        handler = BatchHandler()
        symbols = ["alpha", "beta", "gamma", "delta"]
        for sym in symbols:
            handler.handle(run_id, sym, _description_claim(), "INCONCLUSIVE", store)
        returned_symbols = [item["symbol"] for item in handler.triage_list()]
        assert returned_symbols == symbols

    def test_triage_list_matches_escalations_jsonl(self):
        """In-memory list and persisted jsonl must be in sync."""
        store, run_id, run_dir = _store_and_run()
        handler = BatchHandler()
        claims = [
            ("f1", _description_claim("f1")),
            ("f2", _example_claim("f2")),
            ("f3", _behavioral_claim("f3")),
        ]
        for sym, claim in claims:
            handler.handle(run_id, sym, claim, "INCONCLUSIVE", store)
        triage = handler.triage_list()
        lines = (run_dir / "escalations.jsonl").read_text().splitlines()
        assert len(triage) == len(lines) == 3
        for item, line in zip(triage, lines):
            persisted = json.loads(line)
            assert item["symbol"] == persisted["symbol"]
            assert item["reason"] == persisted["reason"]

    def test_fresh_handler_per_run_no_cross_contamination(self):
        """Two independent BatchHandler instances must not share state."""
        store1, run_id1, _ = _store_and_run()
        store2, run_id2, _ = _store_and_run()
        handler1 = BatchHandler()
        handler2 = BatchHandler()
        handler1.handle(run_id1, "fn_a", _description_claim(), "INCONCLUSIVE", store1)
        handler1.handle(run_id1, "fn_b", _description_claim(), "INCONCLUSIVE", store1)
        handler2.handle(run_id2, "fn_x", _description_claim(), "retry exhausted", store2)
        assert len(handler1.triage_list()) == 2
        assert len(handler2.triage_list()) == 1


# ---------------------------------------------------------------------------
# to_event — ClaimEscalated SSE event
# ---------------------------------------------------------------------------


class TestToEvent:
    def _make_record(
        self,
        symbol: str = "add",
        reason: str = "INCONCLUSIVE",
        claim_summary: str = "[description] Does something.",
        timestamp: str = "2026-06-13T00:00:00+00:00",
    ) -> dict:
        return {
            "symbol": symbol,
            "claim_summary": claim_summary,
            "reason": reason,
            "timestamp": timestamp,
        }

    def test_returns_claim_escalated(self):
        record = self._make_record()
        event = to_event(record)
        assert isinstance(event, ClaimEscalated)

    def test_symbol_field(self):
        record = self._make_record(symbol="sort_items")
        event = to_event(record)
        assert event.symbol == "sort_items"

    def test_reason_field(self):
        record = self._make_record(reason="retry exhausted after 3 attempts")
        event = to_event(record)
        assert event.reason == "retry exhausted after 3 attempts"

    def test_event_type_literal(self):
        """The SSE discriminator must be the literal string 'claim_escalated'."""
        record = self._make_record()
        event = to_event(record)
        assert event.type == "claim_escalated"

    def test_parse_event_round_trip(self):
        """ClaimEscalated from to_event must survive parse_event (full SSE round-trip)."""
        record = self._make_record(symbol="my_fn", reason="INCONCLUSIVE")
        event = to_event(record)
        reparsed = parse_event(event.model_dump_json())
        assert isinstance(reparsed, ClaimEscalated)
        assert reparsed.symbol == "my_fn"
        assert reparsed.reason == "INCONCLUSIVE"


# ---------------------------------------------------------------------------
# Integration: handle → triage_list → to_event pipeline
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_full_pipeline_description_claim(self):
        store, run_id, run_dir = _store_and_run()
        handler = BatchHandler()

        # 1. Escalate a DescriptionClaim (the INCONCLUSIVE path)
        claim = _description_claim(prose="Returns the sum of two integers.")
        handler.handle(run_id, "add", claim, "INCONCLUSIVE", store)

        # 2. Verify persisted record
        record = json.loads((run_dir / "escalations.jsonl").read_text().strip())
        assert record["symbol"] == "add"
        assert "[description]" in record["claim_summary"]
        assert record["reason"] == "INCONCLUSIVE"

        # 3. Verify in-memory triage list
        triage = handler.triage_list()
        assert len(triage) == 1
        assert triage[0]["symbol"] == "add"

        # 4. Convert to SSE event
        event = to_event(triage[0])
        assert isinstance(event, ClaimEscalated)
        assert event.symbol == "add"
        assert event.reason == "INCONCLUSIVE"

    def test_full_pipeline_retry_exhausted(self):
        store, run_id, run_dir = _store_and_run()
        handler = BatchHandler()

        claim = _example_claim("sort_items")
        handler.handle(run_id, "sort_items", claim, "retry exhausted after 3 attempts", store)

        record = json.loads((run_dir / "escalations.jsonl").read_text().strip())
        assert record["symbol"] == "sort_items"
        assert record["reason"] == "retry exhausted after 3 attempts"
        assert "[example]" in record["claim_summary"]

        event = to_event(handler.triage_list()[0])
        reparsed = parse_event(event.model_dump_json())
        assert isinstance(reparsed, ClaimEscalated)
        assert reparsed.symbol == "sort_items"

    def test_mixed_claim_types_full_run(self):
        """Simulate a mini-run with multiple symbols and claim types."""
        store, run_id, run_dir = _store_and_run()
        handler = BatchHandler()

        escalations = [
            ("add", _description_claim("add", "Adds two numbers."), "INCONCLUSIVE"),
            ("sort_items", _example_claim("sort_items"), "retry exhausted after 3 attempts"),
            ("normalize", _behavioral_claim("normalize"), "INCONCLUSIVE"),
        ]
        for sym, claim, reason in escalations:
            handler.handle(run_id, sym, claim, reason, store)

        # All persisted
        lines = (run_dir / "escalations.jsonl").read_text().splitlines()
        assert len(lines) == 3

        # All in triage list
        triage = handler.triage_list()
        assert len(triage) == 3

        # All convertible to SSE events
        events = [to_event(item) for item in triage]
        assert all(isinstance(e, ClaimEscalated) for e in events)
        symbols = [e.symbol for e in events]
        assert symbols == ["add", "sort_items", "normalize"]

    def test_escalation_handler_with_real_local_file_store(self):
        """BatchHandler works end-to-end with a real temp-dir LocalFileStore."""
        with tempfile.TemporaryDirectory() as tmp:
            store = LocalFileStore(root=tmp)
            run_id = store.new_run({"module": "demo.py", "model": "stub"})
            handler = BatchHandler()

            handler.handle(run_id, "greet", _description_claim("greet", "Greets a user."), "INCONCLUSIVE", store)

            esc_path = Path(tmp) / run_id / "escalations.jsonl"
            assert esc_path.exists()
            data = json.loads(esc_path.read_text().strip())
            assert data["symbol"] == "greet"
            assert data["reason"] == "INCONCLUSIVE"
            assert len(handler.triage_list()) == 1
