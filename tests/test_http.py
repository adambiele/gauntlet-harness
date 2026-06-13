"""HTTP adapter tests (Session C).

This environment ships a starlette whose ``TestClient`` needs an unusual httpx variant, so
rather than depend on an HTTP client we drive the adapter's real machinery directly: the
``POST /run`` handler spawns the loop on a background thread and pushes events onto a
thread-safe queue; we drain that queue (exactly as the SSE generator does) and assert the
planted-bug story plus the SSE wire framing. The end-to-end ASGI/SSE transport itself is
verified live via curl during Session C.
"""

from __future__ import annotations

import asyncio
import queue as queue_mod
from pathlib import Path

import pytest
from fastapi import HTTPException

import harness.adapters.http as http_mod
from harness.adapters.events import to_sse
from harness.adapters.http import RunRequest, health, start_run, stream

FIXTURE = str(Path(__file__).resolve().parent.parent / "examples" / "planted_bug.py")


def _drain(run_id: str, timeout: float = 30.0) -> list:
    """Drain a run's queue until the worker thread signals done (mirrors the SSE loop)."""
    q = http_mod._queues[run_id]
    events = []
    while True:
        item = q.get(timeout=timeout)
        if item is http_mod._DONE:
            break
        events.append(item)
    http_mod._queues.pop(run_id, None)  # stream() normally does this
    return events


def test_health():
    assert health()["status"] == "ok"


def test_run_streams_planted_bug(tmp_path, monkeypatch):
    monkeypatch.setattr(http_mod, "RUNS_DIR", str(tmp_path / "runs"))
    run_id = start_run(RunRequest(module_path=FIXTURE, model="stub"))["run_id"]
    events = _drain(run_id)

    types = [e.type for e in events]
    assert "run_started" in types and "run_done" in types

    fails = [
        e for e in events
        if e.type == "verify_result" and e.symbol == "sort_items" and e.verdict == "fail"
    ]
    assert fails and "got [3, 2, 1]" in fails[0].evidence
    assert any(e.type == "claim_escalated" and e.symbol == "sort_items" for e in events)

    # SSE wire framing the dashboard's EventSource listens on.
    sse = to_sse(events[0])
    assert sse.startswith("event: run_started\ndata: ")
    assert sse.endswith("\n\n")


def test_run_with_inline_source(tmp_path, monkeypatch):
    monkeypatch.setattr(http_mod, "RUNS_DIR", str(tmp_path / "runs"))
    source = 'def add(a, b):\n    """Return the sum."""\n    return a + b\n'
    run_id = start_run(RunRequest(module_source=source, model="stub"))["run_id"]
    events = _drain(run_id)
    assert any(e.type == "claim_locked" for e in events)


def test_run_requires_a_target():
    with pytest.raises(HTTPException) as exc:
        start_run(RunRequest(model="stub"))
    assert exc.value.status_code == 400


def test_unknown_run_id_streams_404():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(stream("does-not-exist"))
    assert exc.value.status_code == 404
