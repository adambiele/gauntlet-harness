"""End-to-end tests for the harness loop (Session B).

Drives ``run`` over the planted-bug fixture with the LLM-free ``StubWorker`` and asserts
the verify-by-construction story: the honest function is documented, the planted lie is
caught and escalated, the prose description routes to triage, and a complete ``runs/<id>/``
audit tree is written. Also covers replay-cache semantics at the store boundary.
"""

from __future__ import annotations

from pathlib import Path

from harness.harness import run
from harness.material.loader import load_module
from harness.persistence.store import LocalFileStore
from harness.worker.base import StubWorker

FIXTURE = str(Path(__file__).resolve().parent.parent / "examples" / "planted_bug.py")


def _run(tmp_path, emit=None):
    store = LocalFileStore(root=tmp_path / "runs")
    summary = run(FIXTURE, StubWorker(), store, emit=emit, model="stub")
    return store, summary


def test_end_to_end_summary(tmp_path):
    _store, summary = _run(tmp_path)

    # Honest function fully documented; the buggy one still ships its TRUE signature claim.
    assert "add" in summary["documented"]
    assert "sort_items" in summary["documented"]
    assert "normalize" in summary["documented"]

    # add: signature + example + behavioral = 3 locked. sort_items: signature = 1.
    # normalize: signature = 1.  → 5 verified claims.
    assert summary["verified_claims"] == 5
    # sort_items' false example + normalize's description → 2 escalations.
    assert summary["escalated"] == 2


def test_planted_lie_is_caught_and_escalated(tmp_path):
    events: list = []
    _store, summary = _run(tmp_path, emit=events.append)

    # The example lane FAILs on the reversing sort_items with a real counterexample.
    fails = [
        e for e in events
        if e.type == "verify_result" and e.symbol == "sort_items" and e.verdict == "fail"
    ]
    assert fails, "expected the example lane to FAIL on the planted bug"
    assert "got [3, 2, 1]" in fails[0].evidence

    # Two retries (attempts 2 and 3) then escalation.
    retries = [e for e in events if e.type == "claim_retry" and e.symbol == "sort_items"]
    assert [e.attempt for e in retries] == [2, 3]

    escalated = [
        e for e in events if e.type == "claim_escalated" and e.symbol == "sort_items"
    ]
    assert escalated

    # The triage list (for the dashboard panel) names both unresolved claims.
    triaged = {t["symbol"] for t in summary["triage"]}
    assert triaged == {"sort_items", "normalize"}


def test_only_verified_claims_render(tmp_path):
    store, summary = _run(tmp_path)
    run_dir = Path(store.root) / summary["run_id"]

    # Full audit tree exists.
    assert (run_dir / "manifest.json").is_file()
    assert (run_dir / "docs" / "add.md").is_file()
    assert (run_dir / "alarms.jsonl").is_file()
    assert (run_dir / "escalations.jsonl").is_file()

    add_doc = (run_dir / "docs" / "add.md").read_text(encoding="utf-8")
    assert "✓" in add_doc  # verified claims carry receipts

    # sort_items doc ships its verified signature but NOT the false "sorted ascending" example.
    sort_doc = (run_dir / "docs" / "sort_items.md").read_text(encoding="utf-8")
    assert "## Signature" in sort_doc
    assert "[1, 2, 3]" not in sort_doc  # the lie never rendered


def test_replay_cache_hit_and_miss(tmp_path):
    # First run populates the store with checkpoint receipts.
    store, _summary = _run(tmp_path)

    ctx = load_module(FIXTURE)
    add_hash = ctx.symbols["add"].code_hash
    sort_hash = ctx.symbols["sort_items"].code_hash

    # add's example PASSed → cached and replayable on matching code_hash.
    assert store.load_cached_pass("add", "example", add_hash) is not None
    # sort_items' example FAILed → never cached (only PASSes replay).
    assert store.load_cached_pass("sort_items", "example", sort_hash) is None
    # A changed hash misses.
    assert store.load_cached_pass("add", "example", "deadbeef") is None
