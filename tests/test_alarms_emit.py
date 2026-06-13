"""Tests for harness.alarms.emit (Session A4).

Coverage:
- make_alarm: correct field population, ISO timestamp, no claim_ref default.
- emit: writes exactly one line to alarms.jsonl; returns the same Alarm object.
- to_event: round-trips all fields; alarm_type mapping; AlarmEvent is parseable via
  parse_event.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from harness.adapters.events import AlarmEvent, parse_event
from harness.alarms.emit import emit, make_alarm, to_event
from harness.alarms.types import (
    EXAMPLE_FAILED,
    PHANTOM_API,
    SECRET_LEAK,
    SIGNATURE_MISMATCH,
    Alarm,
    Severity,
)
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


# ---------------------------------------------------------------------------
# make_alarm
# ---------------------------------------------------------------------------


class TestMakeAlarm:
    def test_type_copied_from_alarm_type(self):
        alarm = make_alarm(PHANTOM_API, symbol="foo", message="foo not found")
        assert alarm.type == "PHANTOM_API"

    def test_severity_copied(self):
        alarm = make_alarm(PHANTOM_API, symbol="foo", message="msg")
        assert alarm.severity == Severity.BLOCK

    def test_recommended_action_copied(self):
        alarm = make_alarm(PHANTOM_API, symbol="foo", message="msg")
        assert alarm.recommended_action == PHANTOM_API.recommended_action

    def test_symbol_stored(self):
        alarm = make_alarm(EXAMPLE_FAILED, symbol="my_func", message="expected 1 got 2")
        assert alarm.symbol == "my_func"

    def test_message_stored(self):
        alarm = make_alarm(EXAMPLE_FAILED, symbol="f", message="expected 1 got 2")
        assert alarm.message == "expected 1 got 2"

    def test_claim_ref_none_by_default(self):
        alarm = make_alarm(SIGNATURE_MISMATCH, symbol="g", message="sig wrong")
        assert alarm.claim_ref is None

    def test_claim_ref_stored_when_provided(self):
        alarm = make_alarm(
            SIGNATURE_MISMATCH, symbol="g", message="sig wrong", claim_ref="sig-claim-1"
        )
        assert alarm.claim_ref == "sig-claim-1"

    def test_timestamp_is_iso_utc(self):
        alarm = make_alarm(PHANTOM_API, symbol="x", message="m")
        # Must parse as an ISO datetime without raising.
        from datetime import datetime

        dt = datetime.fromisoformat(alarm.timestamp)
        assert dt.tzinfo is not None, "timestamp must be timezone-aware (UTC)"

    def test_returns_alarm_instance(self):
        alarm = make_alarm(SECRET_LEAK, symbol="x", message="found key")
        assert isinstance(alarm, Alarm)

    def test_different_alarm_types(self):
        for alarm_type in (
            PHANTOM_API,
            SIGNATURE_MISMATCH,
            EXAMPLE_FAILED,
            SECRET_LEAK,
        ):
            alarm = make_alarm(alarm_type, symbol="s", message="m")
            assert alarm.type == alarm_type.name
            assert alarm.severity == alarm_type.severity
            assert alarm.recommended_action == alarm_type.recommended_action


# ---------------------------------------------------------------------------
# emit
# ---------------------------------------------------------------------------


class TestEmit:
    def test_returns_same_alarm_object(self):
        store, run_id, _ = _store_and_run()
        alarm = make_alarm(PHANTOM_API, symbol="foo", message="missing")
        returned = emit(store, run_id, alarm)
        assert returned is alarm

    def test_writes_alarms_jsonl(self):
        store, run_id, run_dir = _store_and_run()
        alarm = make_alarm(EXAMPLE_FAILED, symbol="add", message="expected 3 got 4")
        emit(store, run_id, alarm)
        jsonl_path = run_dir / "alarms.jsonl"
        assert jsonl_path.exists(), "alarms.jsonl not created"

    def test_alarms_jsonl_has_one_line_per_emit(self):
        store, run_id, run_dir = _store_and_run()
        emit(store, run_id, make_alarm(PHANTOM_API, symbol="a", message="m1"))
        emit(store, run_id, make_alarm(EXAMPLE_FAILED, symbol="b", message="m2"))
        lines = (run_dir / "alarms.jsonl").read_text().splitlines()
        assert len(lines) == 2

    def test_jsonl_line_is_valid_json(self):
        store, run_id, run_dir = _store_and_run()
        alarm = make_alarm(SIGNATURE_MISMATCH, symbol="f", message="sig off")
        emit(store, run_id, alarm)
        line = (run_dir / "alarms.jsonl").read_text().strip()
        record = json.loads(line)
        assert isinstance(record, dict)

    def test_jsonl_line_contains_correct_fields(self):
        store, run_id, run_dir = _store_and_run()
        alarm = make_alarm(SIGNATURE_MISMATCH, symbol="parse", message="bad sig", claim_ref="c1")
        emit(store, run_id, alarm)
        record = json.loads((run_dir / "alarms.jsonl").read_text().strip())
        assert record["type"] == "SIGNATURE_MISMATCH"
        assert record["symbol"] == "parse"
        assert record["message"] == "bad sig"
        assert record["claim_ref"] == "c1"
        assert "timestamp" in record
        assert "severity" in record
        assert "recommended_action" in record

    def test_severity_serialised_as_string(self):
        """Severity enum value should be stored as its string value, not as "Severity.HIGH"."""
        store, run_id, run_dir = _store_and_run()
        alarm = make_alarm(SIGNATURE_MISMATCH, symbol="f", message="m")
        emit(store, run_id, alarm)
        record = json.loads((run_dir / "alarms.jsonl").read_text().strip())
        # Severity(str, Enum) values are their string codes: "high", "block", etc.
        assert record["severity"] in ("block", "high", "medium", "low")

    def test_multiple_alarms_each_line_valid(self):
        store, run_id, run_dir = _store_and_run()
        alarms = [
            make_alarm(PHANTOM_API, symbol=f"sym{i}", message=f"msg{i}") for i in range(5)
        ]
        for a in alarms:
            emit(store, run_id, a)
        lines = (run_dir / "alarms.jsonl").read_text().splitlines()
        assert len(lines) == 5
        for line in lines:
            assert isinstance(json.loads(line), dict)


# ---------------------------------------------------------------------------
# to_event
# ---------------------------------------------------------------------------


class TestToEvent:
    def _make(self, alarm_type=EXAMPLE_FAILED, symbol="add", message="expected 3 got 4"):
        return make_alarm(alarm_type, symbol=symbol, message=message)

    def test_returns_alarm_event(self):
        event = to_event(self._make())
        assert isinstance(event, AlarmEvent)

    def test_alarm_type_field_mapped(self):
        """Alarm.type → AlarmEvent.alarm_type (name change at the wire boundary)."""
        alarm = self._make(PHANTOM_API)
        event = to_event(alarm)
        assert event.alarm_type == "PHANTOM_API"

    def test_severity_round_trips(self):
        alarm = self._make(SECRET_LEAK)
        event = to_event(alarm)
        assert event.severity == Severity.BLOCK

    def test_symbol_round_trips(self):
        alarm = self._make(symbol="my_fn")
        event = to_event(alarm)
        assert event.symbol == "my_fn"

    def test_message_round_trips(self):
        alarm = self._make(message="found secret key: sk-abc")
        event = to_event(alarm)
        assert event.message == "found secret key: sk-abc"

    def test_recommended_action_round_trips(self):
        alarm = self._make(EXAMPLE_FAILED)
        event = to_event(alarm)
        assert event.recommended_action == EXAMPLE_FAILED.recommended_action

    def test_timestamp_round_trips(self):
        alarm = self._make()
        event = to_event(alarm)
        assert event.timestamp == alarm.timestamp

    def test_claim_ref_none_by_default(self):
        alarm = self._make()
        event = to_event(alarm)
        assert event.claim_ref is None

    def test_claim_ref_round_trips(self):
        alarm = make_alarm(PHANTOM_API, symbol="s", message="m", claim_ref="ref-42")
        event = to_event(alarm)
        assert event.claim_ref == "ref-42"

    def test_event_type_literal_is_alarm(self):
        """The SSE discriminator field must be the literal string "alarm"."""
        event = to_event(self._make())
        assert event.type == "alarm"

    def test_parse_event_round_trip(self):
        """AlarmEvent produced by to_event must survive parse_event (full SSE round-trip)."""
        alarm = make_alarm(SIGNATURE_MISMATCH, symbol="f", message="sig mismatch", claim_ref="c")
        event = to_event(alarm)
        # Serialise via model_dump_json and re-parse through the union discriminator.
        reparsed = parse_event(event.model_dump_json())
        assert isinstance(reparsed, AlarmEvent)
        assert reparsed.alarm_type == "SIGNATURE_MISMATCH"
        assert reparsed.symbol == "f"

    def test_all_registry_alarm_types(self):
        """to_event works for every entry in the registry."""
        from harness.alarms.types import REGISTRY

        for name, alarm_type in REGISTRY.items():
            alarm = make_alarm(alarm_type, symbol="sym", message="test")
            event = to_event(alarm)
            assert event.alarm_type == name


# ---------------------------------------------------------------------------
# Integration: make_alarm → emit → to_event pipeline
# ---------------------------------------------------------------------------


class TestFullPipeline:
    def test_make_emit_to_event_pipeline(self):
        store, run_id, run_dir = _store_and_run()

        # 1. Build
        alarm = make_alarm(EXAMPLE_FAILED, symbol="sort_items", message="expected [1,2,3] got [3,2,1]")

        # 2. Persist
        returned = emit(store, run_id, alarm)
        assert returned is alarm

        # 3. Verify stored record
        record = json.loads((run_dir / "alarms.jsonl").read_text().strip())
        assert record["type"] == "EXAMPLE_FAILED"
        assert record["symbol"] == "sort_items"

        # 4. Convert to SSE event and round-trip
        event = to_event(alarm)
        reparsed = parse_event(event.model_dump_json())
        assert isinstance(reparsed, AlarmEvent)
        assert reparsed.alarm_type == "EXAMPLE_FAILED"
        assert reparsed.symbol == "sort_items"
        assert reparsed.message == "expected [1,2,3] got [3,2,1]"
        assert reparsed.timestamp == alarm.timestamp
