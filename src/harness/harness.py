"""The harness loop — the convergence point that wires every pillar together.

``run`` is the single orchestrator (design.md §6 / sessions.md Session B). For each
symbol in the target module it runs the verify-by-construction cycle:

    generate → gate → verify → decide → (retry | lock | escalate)

* **generate** — ``worker.generate(symbol, feedback)`` returns structured claims. The
  worker is the *only* swappable, model-backed component; everything below is the harness.
* **gate** — ``guardrails.enforce`` drops/​downgrades unsafe or malformed claims *before*
  any code runs (the Guardrails pillar). Violations become alarms.
* **verify** — ``checkpoints.runner.verify`` runs each surviving claim against the real
  code in the subprocess sandbox (the Checkpoints pillar). Reality adjudicates.
* **decide** — partition by verdict: PASS → lock; INCONCLUSIVE → escalate; FAIL → retry.
* **retry** — regenerate with hybrid feedback (the failure alarms) up to ``max_attempts``
  per symbol; still failing → escalate to triage (the Escalation pillar).

Only locked (PASS) claims are rendered into the doc — "no unverified claim ships", by
construction. Every step is persisted to the immutable ``runs/<id>/`` store and traced
through OTel spans (the Observability pillar). The ``emit`` callback streams typed events
(``adapters/events``) for the live dashboard.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from harness.adapters.events import (
    ClaimEscalated,
    ClaimLocked,
    ClaimRetry,
    Generated,
    GateResult,
    MetricUpdate,
    RunDone,
    RunStarted,
    SymbolDone,
    SymbolStarted,
    VerifyResult,
)
from harness.alarms.emit import emit as persist_alarm
from harness.alarms.emit import make_alarm
from harness.alarms.emit import to_event as alarm_to_event
from harness.alarms.types import (
    BEHAVIOR_CONTRADICTION,
    EXAMPLE_FAILED,
    SIGNATURE_MISMATCH,
    Alarm,
)
from harness.checkpoints.runner import verify
from harness.contracts import CheckpointResult, Claim, SymbolInfo, Verdict
from harness.guardrails.enforce import enforce
from harness.material.loader import load_module
from harness.material.renderer import render_doc, render_index
from harness.observability import (
    ATTR_COST_USD,
    ATTR_MODEL,
    SPAN_DECIDE,
    SPAN_RUN,
    SPAN_SYMBOL,
    init_telemetry,
    span,
)
from harness.persistence.store import Store
from harness.worker.base import Worker

__all__ = ["run", "DEFAULT_MAX_ATTEMPTS"]

DEFAULT_MAX_ATTEMPTS = 3

# claim.type → the verification lane that handles it (None = no mechanical lane).
_LANE_FOR_TYPE: dict[str, str] = {
    "signature": "signature",
    "example": "example",
    "behavioral": "behavioral",
}

# lane → the alarm raised when that lane returns FAIL (fed back to the worker on retry).
_ALARM_FOR_LANE = {
    "signature": SIGNATURE_MISMATCH,
    "example": EXAMPLE_FAILED,
    "behavioral": BEHAVIOR_CONTRADICTION,
}


def _claim_key(claim: Claim) -> tuple[str, str, str]:
    """Stable identity for a claim, so a PASS isn't locked twice across retries."""
    return (claim.type, claim.target, getattr(claim, "prose", ""))


def _claim_ref(claim: Claim) -> str:
    return f"{claim.type}:{claim.target}"


def run(
    module_path: str,
    worker: Worker,
    store: Store,
    emit: Optional[Callable[[Any], None]] = None,
    *,
    model: str = "stub",
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> dict:
    """Run the full verify-by-construction loop over ``module_path``.

    Args:
        module_path: Path to the target ``.py`` (read via ``ast``, never imported).
        worker:      The (swappable) claim generator — Stub / Claude / Local.
        store:       Persistence + audit store (``runs/<id>/``).
        emit:        Optional sink for typed SSE events; defaults to a no-op.
        model:       Label recorded in the manifest / ``RunStarted`` (e.g. ``"opus"``).
        max_attempts: Max generate→verify cycles per symbol before escalating fails.

    Returns:
        A summary dict: ``run_id``, counts, documented symbols, and the triage list.
    """
    emit = emit or (lambda _event: None)
    aggregator = init_telemetry("harness")
    metrics_start = len(aggregator.records)  # slice point — isolate this run's spans

    ctx = load_module(module_path)
    from harness.escalation.handlers import BatchHandler  # local: keeps import graph flat

    handler = BatchHandler()

    run_id = store.new_run(
        {"module": module_path, "model": model, "symbols": list(ctx.symbols)}
    )
    emit(RunStarted(run_id=run_id, module=module_path, model=model))

    verified_claims = 0
    escalated = 0
    documented: list[SymbolInfo] = []

    with span(SPAN_RUN, **{ATTR_MODEL: model}):
        for name, symbol in ctx.symbols.items():
            with span(SPAN_SYMBOL):
                emit(SymbolStarted(symbol=name))
                locked: list[tuple[Claim, CheckpointResult]] = []
                locked_keys: set[tuple[str, str, str]] = set()
                feedback: Optional[list[Alarm]] = None
                attempt = 1

                while True:
                    # ── generate ─────────────────────────────────────────────
                    claims = worker.generate(symbol, feedback)
                    store.write_claims(run_id, name, claims)
                    emit(Generated(symbol=name, claim_count=len(claims)))

                    # ── gate ─────────────────────────────────────────────────
                    cleaned, gate_alarms = enforce(claims, ctx)
                    emit(GateResult(symbol=name, violations=[a.type for a in gate_alarms]))
                    for a in gate_alarms:
                        persist_alarm(store, run_id, a)
                        emit(alarm_to_event(a))

                    # ── verify ───────────────────────────────────────────────
                    results: list[tuple[Claim, CheckpointResult]] = []
                    for claim in cleaned:
                        lane = _LANE_FOR_TYPE.get(claim.type)
                        result = None
                        if lane is not None:
                            cached = store.load_cached_pass(name, lane, symbol.code_hash)
                            if cached is not None:
                                result = cached  # replay hit — skip re-execution
                        if result is None:
                            result = verify(claim, symbol, ctx.module_source)
                            store.write_checkpoint(run_id, result)
                        emit(
                            VerifyResult(
                                symbol=name,
                                claim_type=claim.type,
                                lane=result.lane,
                                verdict=result.verdict.value,
                                evidence=result.evidence,
                            )
                        )
                        results.append((claim, result))

                    # ── decide ───────────────────────────────────────────────
                    with span(SPAN_DECIDE):
                        failed: list[tuple[Claim, CheckpointResult]] = []
                        attempt_fail_alarms: list[Alarm] = []
                        for claim, result in results:
                            if result.verdict == Verdict.PASS:
                                key = _claim_key(claim)
                                if key not in locked_keys:
                                    locked_keys.add(key)
                                    locked.append((claim, result))
                                    emit(
                                        ClaimLocked(
                                            symbol=name,
                                            claim_type=claim.type,
                                            prose=claim.prose,
                                        )
                                    )
                            elif result.verdict == Verdict.INCONCLUSIVE:
                                handler.handle(run_id, name, claim, "INCONCLUSIVE", store)
                                emit(ClaimEscalated(symbol=name, reason="INCONCLUSIVE"))
                                escalated += 1
                            else:  # FAIL
                                alarm = make_alarm(
                                    _ALARM_FOR_LANE.get(result.lane, EXAMPLE_FAILED),
                                    name,
                                    result.evidence,
                                    claim_ref=_claim_ref(claim),
                                )
                                persist_alarm(store, run_id, alarm)
                                emit(alarm_to_event(alarm))
                                failed.append((claim, result))
                                attempt_fail_alarms.append(alarm)

                    # ── retry / escalate ─────────────────────────────────────
                    if not failed:
                        break
                    if attempt >= max_attempts:
                        for claim, _result in failed:
                            handler.handle(
                                run_id,
                                name,
                                claim,
                                f"retry exhausted after {attempt} attempts",
                                store,
                            )
                            emit(ClaimEscalated(symbol=name, reason="retry exhausted"))
                            escalated += 1
                        break
                    emit(
                        ClaimRetry(
                            symbol=name,
                            attempt=attempt + 1,
                            reason=f"{len(failed)} claim(s) failed verification",
                        )
                    )
                    # hybrid feedback: gate + verification failures from this attempt.
                    feedback = gate_alarms + attempt_fail_alarms
                    attempt += 1

                # ── render the survivors ─────────────────────────────────────
                if locked:
                    doc = render_doc(symbol, locked)
                    store.write_doc(run_id, name, doc)
                    documented.append(symbol)
                    verified_claims += len(locked)
                emit(SymbolDone(symbol=name))

    # ── run-level index + metrics ────────────────────────────────────────────
    store.write_doc(run_id, "_index", render_index(documented))
    _emit_metrics(aggregator.records[metrics_start:], emit)
    emit(RunDone(run_id=run_id, verified_count=verified_claims, escalated_count=escalated))

    return {
        "run_id": run_id,
        "module": module_path,
        "model": model,
        "symbols": list(ctx.symbols),
        "verified_claims": verified_claims,
        "escalated": escalated,
        "documented": [s.name for s in documented],
        "triage": handler.triage_list(),
    }


def _emit_metrics(records: list[dict], emit: Callable[[Any], None]) -> None:
    """Project this run's OTel spans into ``MetricUpdate`` events for the dashboard.

    Metric names follow the convention the dashboard groups on (drift-log):
    ``verify.<lane>.duration_ms`` / ``verify.<lane>.p95_ms`` / ``generate.cost_usd``.
    """
    for lane in ("signature", "example", "behavioral"):
        durs = sorted(
            r["duration_ms"] for r in records if r["name"] == f"verify.{lane}"
        )
        if not durs:
            continue
        avg = sum(durs) / len(durs)
        p95 = durs[min(len(durs) - 1, int(0.95 * len(durs)))]
        emit(MetricUpdate(name=f"verify.{lane}.duration_ms", value=round(avg, 3)))
        emit(MetricUpdate(name=f"verify.{lane}.p95_ms", value=round(p95, 3)))

    total_cost = sum(
        float(r["attrs"].get(ATTR_COST_USD, 0.0))
        for r in records
        if r["name"] == "generate"
    )
    emit(MetricUpdate(name="generate.cost_usd", value=round(total_cost, 6)))
