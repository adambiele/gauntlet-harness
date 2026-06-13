"""Adapters — wire formats and entry points.

Session 0 ships the SSE event contract (``events.py``). The CLI and FastAPI/HTTP
adapters are later sessions (B and C).
"""

from harness.adapters.events import Event, parse_event, to_sse

__all__ = ["Event", "parse_event", "to_sse"]
