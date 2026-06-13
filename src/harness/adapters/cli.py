"""Command-line driver for the harness loop.

    python -m harness.adapters.cli examples/planted_bug.py --worker stub

Streams each loop event to stdout as it happens, then prints the run summary and the
triage list. Uses ``LocalFileStore`` (writes ``runs/<id>/``) and ``make_worker`` so the
active model is a config-time choice (``--worker stub|sonnet|haiku|openai|qwen``).
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Optional, Sequence

from harness.harness import run
from harness.persistence.store import LocalFileStore
from harness.worker.llm_worker import make_worker

# Compact one-line glyphs per event type for a readable live trace.
_GLYPH = {
    "run_started": "▶",
    "symbol_started": "◆",
    "generated": "✎",
    "gate_result": "⛬",
    "verify_result": "·",
    "claim_locked": "✓",
    "claim_retry": "↻",
    "claim_escalated": "⚑",
    "alarm": "🔔",
    "symbol_done": "◇",
    "metric_update": "📊",
    "run_done": "■",
}


def _format_event(event: Any) -> str:
    """Render one event as a single readable line."""
    etype = getattr(event, "type", "event")
    glyph = _GLYPH.get(etype, " ")
    data = event.model_dump()
    data.pop("type", None)
    # Keep the most relevant fields up front for the common events.
    if etype == "verify_result":
        return f"  {glyph} verify[{data['lane']}] {data['symbol']} → {data['verdict'].upper()}: {data['evidence'][:80]}"
    if etype == "claim_locked":
        return f"  {glyph} LOCKED {data['symbol']} [{data['claim_type']}] {data['prose'][:60]}"
    if etype == "claim_escalated":
        return f"  {glyph} ESCALATED {data['symbol']} — {data['reason']}"
    if etype == "claim_retry":
        return f"  {glyph} RETRY {data['symbol']} (attempt {data['attempt']}) — {data['reason']}"
    if etype == "alarm":
        return f"  {glyph} ALARM {data['alarm_type']} [{data['severity']}] {data['symbol']}: {data['message'][:70]}"
    return f"  {glyph} {etype}: {json.dumps(data, default=str)}"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="harness",
        description="Run the Verified Documentation Harness over a Python module.",
    )
    parser.add_argument("module_path", help="Path to the target .py file (never imported).")
    parser.add_argument(
        "--worker",
        default="stub",
        help=(
            "Worker/model: stub | demo[:<model>] | sonnet | claude | haiku | openai | gpt | "
            "qwen | local (default: stub). 'demo' seeds a false claim then lets a live model "
            "correct it — the deterministic catch-and-recover arc."
        ),
    )
    parser.add_argument(
        "--runs-dir",
        default="runs",
        help="Root directory for the run store (default: ./runs).",
    )
    args = parser.parse_args(argv)

    store = LocalFileStore(root=args.runs_dir)
    worker = make_worker(args.worker)

    print(f"Running harness on {args.module_path} with worker '{args.worker}'\n")
    summary = run(
        args.module_path,
        worker,
        store,
        emit=lambda event: print(_format_event(event)),
        model=args.worker,
    )

    print("\n=== SUMMARY ===")
    print(f"  run_id          : {summary['run_id']}")
    print(f"  documented      : {', '.join(summary['documented']) or '(none)'}")
    print(f"  verified claims : {summary['verified_claims']}")
    print(f"  escalated       : {summary['escalated']}")
    print(f"  run store       : {args.runs_dir}/{summary['run_id']}/")

    if summary["triage"]:
        print("\n=== TRIAGE (needs a human) ===")
        for item in summary["triage"]:
            print(f"  ⚑ {item['symbol']}: {item['claim_summary']} — {item['reason']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
