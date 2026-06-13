"""Foundation wiring — store/replay, SSE events, observability, alarms, stub worker."""

import json

from harness.adapters.events import (
    RunStarted,
    VerifyResult,
    parse_event,
    to_sse,
)
from harness.alarms.types import REGISTRY, Alarm, Severity
from harness.contracts import (
    CheckpointResult,
    SignatureClaim,
    SymbolInfo,
    Verdict,
)
from harness.observability import init_telemetry, span, ATTR_LANE, ATTR_VERDICT
from harness.persistence.store import LocalFileStore
from harness.worker.base import StubWorker


# -- persistence + replay ---------------------------------------------------------
def _result(symbol="add", lane="signature", code_hash="h1", verdict=Verdict.PASS):
    return CheckpointResult(
        symbol=symbol,
        claim=SignatureClaim(type="signature", target=symbol, prose="p", claimed_signature="(a, b)"),
        verdict=verdict,
        evidence="ok",
        code_hash=code_hash,
        lane=lane,
        timestamp="2026-06-13T00:00:00Z",
        duration_ms=1.2,
    )


def test_store_run_round_trip(tmp_path):
    store = LocalFileStore(root=tmp_path)
    run_id = store.new_run({"module": "demo.py", "model": "stub"})
    assert (tmp_path / run_id / "manifest.json").is_file()

    store.write_claims(run_id, "add", [_result().claim])
    store.write_checkpoint(run_id, _result())
    store.append_alarm(run_id, {"type": "PHANTOM_API"})
    store.append_escalation(run_id, {"symbol": "add"})
    store.write_doc(run_id, "add", "# add\n")

    assert (tmp_path / run_id / "claims" / "add.json").is_file()
    assert (tmp_path / run_id / "checkpoints" / "add" / "signature.json").is_file()
    assert (tmp_path / run_id / "alarms.jsonl").read_text().strip()
    assert (tmp_path / run_id / "docs" / "add.md").is_file()


def test_replay_hits_on_matching_hash_misses_on_change(tmp_path):
    store = LocalFileStore(root=tmp_path)
    run_id = store.new_run({"module": "demo.py"})
    store.write_checkpoint(run_id, _result(code_hash="h1"))

    hit = store.load_cached_pass("add", "signature", "h1")
    assert hit is not None and hit.verdict == Verdict.PASS

    miss = store.load_cached_pass("add", "signature", "h2")
    assert miss is None


def test_replay_ignores_non_pass(tmp_path):
    store = LocalFileStore(root=tmp_path)
    run_id = store.new_run({"module": "demo.py"})
    store.write_checkpoint(run_id, _result(verdict=Verdict.FAIL, code_hash="h1"))
    assert store.load_cached_pass("add", "signature", "h1") is None


# -- SSE events -------------------------------------------------------------------
def test_event_to_sse_and_parse_round_trip():
    ev = RunStarted(run_id="run-0001", module="demo.py", model="stub")
    wire = to_sse(ev)
    assert wire.startswith("event: run_started\n")
    assert wire.endswith("\n\n")

    data_line = [l for l in wire.splitlines() if l.startswith("data: ")][0]
    payload = data_line[len("data: "):]
    back = parse_event(json.loads(payload))
    assert isinstance(back, RunStarted)
    assert back.run_id == "run-0001"


def test_verify_result_event_parses_by_discriminator():
    ev = VerifyResult(
        symbol="add", claim_type="example", lane="example", verdict="pass", evidence="ok"
    )
    back = parse_event(ev.model_dump())
    assert isinstance(back, VerifyResult)
    assert back.lane == "example"


# -- observability ----------------------------------------------------------------
def test_aggregator_records_spans():
    agg = init_telemetry("harness-test")
    agg.reset()
    with span("verify.example", **{ATTR_LANE: "example", ATTR_VERDICT: "pass"}):
        pass
    records = agg.by_name("verify.example")
    assert len(records) == 1
    assert records[0]["attrs"][ATTR_LANE] == "example"
    assert records[0]["duration_ms"] >= 0


# -- alarms -----------------------------------------------------------------------
def test_alarm_registry_complete():
    expected = {
        "PHANTOM_API", "SIGNATURE_MISMATCH", "EXAMPLE_FAILED", "BEHAVIOR_CONTRADICTION",
        "MALFORMED_CLAIM", "UNVERIFIABLE_CLAIM", "SECRET_LEAK",
    }
    assert set(REGISTRY) == expected
    assert REGISTRY["PHANTOM_API"].severity is Severity.BLOCK
    assert REGISTRY["UNVERIFIABLE_CLAIM"].severity is Severity.LOW


def test_alarm_dataclass_shape():
    a = Alarm(
        type="PHANTOM_API",
        severity=Severity.BLOCK,
        symbol="ghost",
        claim_ref=None,
        message="symbol does not exist",
        recommended_action=REGISTRY["PHANTOM_API"].recommended_action,
        timestamp="2026-06-13T00:00:00Z",
    )
    assert a.severity is Severity.BLOCK


# -- stub worker ------------------------------------------------------------------
def _symbol(name):
    return SymbolInfo(
        name=name, signature="(xs)", source=f"def {name}(xs): ...",
        docstring=None, lineno=1, code_hash="h",
    )


def test_stub_worker_plants_wrong_claim_for_sort_items():
    claims = StubWorker().generate(_symbol("sort_items"))
    example = [c for c in claims if c.type == "example"][0]
    # The planted lie: claims sorted ascending.
    assert example.cases[0].args == [[3, 1, 2]]
    assert example.cases[0].expected == [1, 2, 3]


def test_stub_worker_generic_symbol():
    claims = StubWorker().generate(_symbol("whatever"))
    assert any(c.type == "signature" for c in claims)
