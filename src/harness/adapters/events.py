"""SSE wire contract — typed events for the live loop stream (design.md §9).

Both the HTTP adapter (backend, emits) and the dashboard (frontend, parses) depend on
these shapes, so they are part of the frozen contract. Each event is a pydantic model
with a literal ``type`` discriminator; ``Event`` is the parse-side union.

``to_sse`` renders one event in the Server-Sent-Events wire format::

    event: <type>
    data: <json>
    \n
"""

from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field, TypeAdapter

from harness.alarms.types import Severity

__all__ = [
    "RunStarted",
    "SymbolStarted",
    "Generated",
    "GateResult",
    "VerifyResult",
    "ClaimLocked",
    "ClaimRetry",
    "ClaimEscalated",
    "AlarmEvent",
    "SymbolDone",
    "MetricUpdate",
    "RunDone",
    "Event",
    "parse_event",
    "to_sse",
]


class RunStarted(BaseModel):
    type: Literal["run_started"] = "run_started"
    run_id: str
    module: str
    model: str


class SymbolStarted(BaseModel):
    type: Literal["symbol_started"] = "symbol_started"
    symbol: str


class Generated(BaseModel):
    type: Literal["generated"] = "generated"
    symbol: str
    claim_count: int


class GateResult(BaseModel):
    type: Literal["gate_result"] = "gate_result"
    symbol: str
    violations: list = Field(default_factory=list)


class VerifyResult(BaseModel):
    type: Literal["verify_result"] = "verify_result"
    symbol: str
    claim_type: str
    lane: str
    verdict: str
    evidence: str


class ClaimLocked(BaseModel):
    type: Literal["claim_locked"] = "claim_locked"
    symbol: str
    claim_type: str
    prose: str


class ClaimRetry(BaseModel):
    type: Literal["claim_retry"] = "claim_retry"
    symbol: str
    attempt: int
    reason: str


class ClaimEscalated(BaseModel):
    type: Literal["claim_escalated"] = "claim_escalated"
    symbol: str
    reason: str


class AlarmEvent(BaseModel):
    """An alarm crossing the wire. Mirrors ``alarms.types.Alarm`` field-for-field."""

    type: Literal["alarm"] = "alarm"
    alarm_type: str
    severity: Severity
    symbol: str
    claim_ref: Optional[str] = None
    message: str
    recommended_action: str
    timestamp: str


class SymbolDone(BaseModel):
    type: Literal["symbol_done"] = "symbol_done"
    symbol: str


class MetricUpdate(BaseModel):
    type: Literal["metric_update"] = "metric_update"
    name: str
    value: float


class RunDone(BaseModel):
    type: Literal["run_done"] = "run_done"
    run_id: str
    verified_count: int
    escalated_count: int


Event = Annotated[
    Union[
        RunStarted,
        SymbolStarted,
        Generated,
        GateResult,
        VerifyResult,
        ClaimLocked,
        ClaimRetry,
        ClaimEscalated,
        AlarmEvent,
        SymbolDone,
        MetricUpdate,
        RunDone,
    ],
    Field(discriminator="type"),
]

_EVENT_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)


def parse_event(data: object) -> Event:
    """Validate a decoded dict (or JSON string) into the matching ``Event`` model."""
    if isinstance(data, (str, bytes, bytearray)):
        return _EVENT_ADAPTER.validate_json(data)
    return _EVENT_ADAPTER.validate_python(data)


def to_sse(event: BaseModel) -> str:
    """Render an event in SSE wire format (``event:`` + ``data:`` + blank line)."""
    event_type = getattr(event, "type", "message")
    payload = event.model_dump_json()
    return f"event: {event_type}\ndata: {payload}\n\n"
