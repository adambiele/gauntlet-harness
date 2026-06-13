"""Observability — OpenTelemetry as the single telemetry source (design.md §10).

From hour one, all timing/cost/verdict signal flows through OTel spans. This module:

* ``init_telemetry`` — sets up the OTel SDK with a ``ConsoleSpanExporter`` (OTLP →
  Langfuse is a later flip-of-a-switch) **and** the in-process ``Aggregator`` so the
  dashboard metrics panel has a feed without leaving the process.
* ``span`` — a context-manager helper that opens a span and stamps attributes on it.
* ``Aggregator`` — a lightweight ``SpanProcessor`` recording ``(name, duration_ms,
  attrs)`` per span so a later panel can compute count / avg / p95 / cost.

Frozen conventions (the span tree + attribute names) are module constants below so every
producer/consumer agrees. These are part of the contract.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Optional

from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

__all__ = [
    "init_telemetry",
    "span",
    "Aggregator",
    "get_aggregator",
    "SPAN_RUN",
    "SPAN_SYMBOL",
    "SPAN_GENERATE",
    "SPAN_GATE",
    "SPAN_VERIFY",
    "SPAN_DECIDE",
    "SPAN_NAMES",
    "ATTR_MODEL",
    "ATTR_TOKENS_IN",
    "ATTR_TOKENS_OUT",
    "ATTR_COST_USD",
    "ATTR_VERDICT",
    "ATTR_LANE",
    "ATTR_DURATION_MS",
    "ATTR_KEYS",
]

# --------------------------------------------------------------------------------------
# FROZEN CONVENTIONS — span tree:  run -> symbol -> {generate, gate, verify.<lane>, decide}
# --------------------------------------------------------------------------------------
SPAN_RUN = "run"
SPAN_SYMBOL = "symbol"
SPAN_GENERATE = "generate"
SPAN_GATE = "gate"
SPAN_VERIFY = "verify"  # verify lanes are named "verify.<lane>" e.g. "verify.example"
SPAN_DECIDE = "decide"

SPAN_NAMES = (SPAN_RUN, SPAN_SYMBOL, SPAN_GENERATE, SPAN_GATE, SPAN_VERIFY, SPAN_DECIDE)

# Attribute keys stamped on spans (and read back by the aggregator / dashboard).
ATTR_MODEL = "model"
ATTR_TOKENS_IN = "tokens_in"
ATTR_TOKENS_OUT = "tokens_out"
ATTR_COST_USD = "cost_usd"
ATTR_VERDICT = "verdict"
ATTR_LANE = "lane"
ATTR_DURATION_MS = "duration_ms"

ATTR_KEYS = (
    ATTR_MODEL,
    ATTR_TOKENS_IN,
    ATTR_TOKENS_OUT,
    ATTR_COST_USD,
    ATTR_VERDICT,
    ATTR_LANE,
    ATTR_DURATION_MS,
)


class Aggregator(SpanProcessor):
    """In-process recorder: captures ``(name, duration_ms, attrs)`` for every ended span.

    A later metrics panel computes count / avg / p95 / total-cost from ``records``. This
    is the first of the "two consumers off the same spans" (design.md §10); the second
    (OTLP → Langfuse) is added later.
    """

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def on_start(self, span: Any, parent_context: Any = None) -> None:  # noqa: D401
        # Nothing to do on start; we record on end when timing is known.
        return None

    def on_end(self, span: ReadableSpan) -> None:
        attrs = dict(span.attributes or {})
        if span.end_time is not None and span.start_time is not None:
            duration_ms = (span.end_time - span.start_time) / 1_000_000
        else:
            duration_ms = float(attrs.get(ATTR_DURATION_MS, 0.0))
        self.records.append(
            {"name": span.name, "duration_ms": duration_ms, "attrs": attrs}
        )

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return True

    # -- convenience read API for the metrics panel -------------------------------
    def by_name(self, name: str) -> list[dict[str, Any]]:
        return [r for r in self.records if r["name"] == name]

    def reset(self) -> None:
        self.records.clear()


# Module-level singletons, wired by ``init_telemetry``.
_aggregator: Optional[Aggregator] = None
_initialized = False


def init_telemetry(service_name: str) -> Aggregator:
    """Initialize the OTel SDK (Console exporter + in-process Aggregator).

    Idempotent: repeated calls return the existing aggregator without re-registering a
    provider (OTel only honours the first ``set_tracer_provider``). Returns the
    ``Aggregator`` so callers/tests can read metrics directly.
    """
    global _aggregator, _initialized
    if _initialized and _aggregator is not None:
        return _aggregator

    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    aggregator = Aggregator()
    provider.add_span_processor(aggregator)

    # set_tracer_provider only takes effect once per process; guard so tests that call
    # init_telemetry repeatedly don't warn/no-op into a different aggregator.
    try:
        trace.set_tracer_provider(provider)
    except Exception:  # pragma: no cover - defensive; OTel logs rather than raises
        pass

    _aggregator = aggregator
    _initialized = True
    return aggregator


def get_aggregator() -> Optional[Aggregator]:
    """Return the active aggregator (or ``None`` if ``init_telemetry`` hasn't run)."""
    return _aggregator


@contextmanager
def span(name: str, **attrs: Any) -> Iterator[Any]:
    """Open a span named ``name``, stamping ``attrs`` (use the ``ATTR_*`` keys).

    Usage::

        with span("verify.example", lane="example", verdict="pass"):
            ...

    Works before ``init_telemetry`` too (falls back to OTel's default no-op tracer).
    """
    tracer = trace.get_tracer("harness")
    with tracer.start_as_current_span(name) as otel_span:
        for key, value in attrs.items():
            if value is not None:
                otel_span.set_attribute(key, value)
        yield otel_span
