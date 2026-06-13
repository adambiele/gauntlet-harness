"""FastAPI adapter — drive the harness loop over HTTP + stream events as SSE.

Two endpoints back the dashboard (design.md §9):

* ``POST /run`` — accept ``{module_path | module_source, model}``, start the (synchronous,
  subprocess-spawning) loop on a background thread, and return a ``run_id`` the client uses
  to open the stream. Events the loop ``emit``s are pushed onto a per-run thread-safe queue.
* ``GET /run/{run_id}/stream`` — a ``text/event-stream`` that drains that queue and yields
  each event via ``to_sse`` (``event: <type>\\ndata: <json>``), with periodic heartbeats.

The loop is sync and CPU/subprocess-bound, so it must NOT run on the event loop. The bridge
is a plain ``queue.Queue`` (thread-safe puts from the worker thread) drained by the async
generator through ``run_in_executor`` — no blocking the event loop, no lost events (the
queue buffers everything produced before the client connects).

Run locally::

    HARNESS_RUNS_DIR=runs uvicorn harness.adapters.http:app --reload
    # or: python -m harness.adapters.http   (binds $PORT, 0.0.0.0 — Render-ready)
"""

from __future__ import annotations

import ast
import asyncio
import functools
import os
import queue
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from harness.adapters.events import AlarmEvent, to_sse
from harness.alarms.types import Severity
from harness.harness import run
from harness.persistence.store import LocalFileStore
from harness.worker.llm_worker import make_worker

RUNS_DIR = os.environ.get("HARNESS_RUNS_DIR", "runs")
# Directory of bundled example modules the dashboard picker lists. Relative to the
# process CWD (``/app`` in the Docker image, where ``examples/`` is copied alongside src).
EXAMPLES_DIR = os.environ.get("HARNESS_EXAMPLES_DIR", "examples")
HEARTBEAT_SECONDS = 15

app = FastAPI(title="Verified Documentation Harness")

# CORS: the Vercel SPA is a different origin. ``*`` is fine for the sprint (no credentials).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Sentinel pushed by the worker thread to signal "stream complete".
_DONE = object()
# run_id → event queue. Created at POST time, drained (and removed) by the stream.
_queues: dict[str, "queue.Queue"] = {}


class RunRequest(BaseModel):
    """Body for ``POST /run``. Provide a server-side ``module_path`` or inline source."""

    module_path: Optional[str] = None
    module_source: Optional[str] = None
    model: str = "stub"


def _error_event(message: str) -> AlarmEvent:
    """Wrap a top-level run failure as an ``alarm`` event the dashboard already renders."""
    return AlarmEvent(
        alarm_type="HARNESS_ERROR",
        severity=Severity.BLOCK,
        symbol="(run)",
        claim_ref=None,
        message=message[:300],
        recommended_action="check the target module and the server logs",
        timestamp=datetime.now(tz=timezone.utc).isoformat(),
    )


@app.get("/health")
def health() -> dict:
    """Liveness probe (Render health check)."""
    return {"status": "ok", "runs_dir": RUNS_DIR}


@app.get("/examples")
def list_examples() -> list[dict]:
    """List bundled example modules for the dashboard picker.

    One entry per ``.py`` file in ``EXAMPLES_DIR``, each with a relative ``path`` (sent
    back verbatim as ``module_path`` on ``POST /run``) and a one-line ``title`` taken from
    the module docstring. Files are read as text and parsed with ``ast`` only — never
    imported (same no-import contract as the loader). Returns ``[]`` if the directory is
    missing or unreadable.
    """
    out: list[dict] = []
    try:
        names = sorted(os.listdir(EXAMPLES_DIR))
    except OSError:
        return out
    for fn in names:
        if not fn.endswith(".py") or fn.startswith("_"):
            continue
        path = os.path.join(EXAMPLES_DIR, fn)
        title = ""
        try:
            source = open(path, encoding="utf-8").read()
            doc = ast.get_docstring(ast.parse(source))
            if doc:
                title = doc.strip().splitlines()[0]
        except (OSError, SyntaxError, ValueError):
            pass
        out.append({"name": fn, "path": path, "title": title})
    return out


@app.post("/run")
def start_run(req: RunRequest) -> dict:
    """Start a run on a background thread; return the ``run_id`` to open the stream with."""
    if not req.module_path and not req.module_source:
        raise HTTPException(status_code=400, detail="provide module_path or module_source")

    run_id = uuid.uuid4().hex[:12]
    q: "queue.Queue" = queue.Queue()
    _queues[run_id] = q

    # Inline source → write to a temp .py the loader can read (it never imports it).
    cleanup_path: Optional[str] = None
    if req.module_source is not None:
        tmp = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8")
        tmp.write(req.module_source)
        tmp.close()
        module_path = tmp.name
        cleanup_path = tmp.name
    else:
        module_path = req.module_path  # type: ignore[assignment]

    model = req.model

    def _worker() -> None:
        store = LocalFileStore(root=RUNS_DIR)
        try:
            run(module_path, make_worker(model), store, emit=q.put, model=model)
        except Exception as exc:  # noqa: BLE001 — surface any failure to the client
            q.put(_error_event(f"{type(exc).__name__}: {exc}"))
        finally:
            q.put(_DONE)
            if cleanup_path:
                try:
                    os.unlink(cleanup_path)
                except OSError:
                    pass

    threading.Thread(target=_worker, name=f"run-{run_id}", daemon=True).start()
    return {"run_id": run_id}


@app.get("/run/{run_id}/stream")
async def stream(run_id: str) -> StreamingResponse:
    """Stream the run's events as SSE until the loop signals done."""
    q = _queues.get(run_id)
    if q is None:
        raise HTTPException(status_code=404, detail="unknown run id (or already streamed)")

    async def gen():
        loop = asyncio.get_event_loop()
        try:
            while True:
                try:
                    item = await loop.run_in_executor(
                        None, functools.partial(q.get, timeout=HEARTBEAT_SECONDS)
                    )
                except queue.Empty:
                    yield ": heartbeat\n\n"  # SSE comment — keeps proxies/EventSource alive
                    continue
                if item is _DONE:
                    break
                yield to_sse(item)
        finally:
            _queues.pop(run_id, None)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable proxy buffering (nginx/Render)
        },
    )


def main() -> None:
    """Entrypoint for ``python -m harness.adapters.http`` — binds ``$PORT`` on 0.0.0.0."""
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("harness.adapters.http:app", host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
