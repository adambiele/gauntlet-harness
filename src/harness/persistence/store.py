"""Persistence — the immutable per-run audit store (design.md §8).

The ``runs/<run_id>/`` tree *is* the audit log: claims in, checkpoint receipts out,
append-only alarms/escalations, and the rendered doc projection. Replay is keyed by
``code_hash`` — a cached PASS for a symbol+lane is reused iff the symbol's source is
unchanged.

This module ships the abstract ``Store`` interface **and** a minimal but fully working
``LocalFileStore``. Durable backends (Render persistent disk, GCS) are later swaps behind
the same interface.

    runs/<run_id>/
      manifest.json
      claims/<symbol>.json
      checkpoints/<symbol>/<lane>.json
      alarms.jsonl
      escalations.jsonl
      docs/<symbol>.md
"""

from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Optional

from harness.contracts import CheckpointResult, Claim, Verdict

__all__ = ["Store", "LocalFileStore"]


class Store(ABC):
    """Abstract persistence + audit store. See ``LocalFileStore`` for the layout."""

    @abstractmethod
    def new_run(self, manifest: dict) -> str:
        """Create a new run, write its manifest, and return the ``run_id``."""

    @abstractmethod
    def write_claims(self, run_id: str, symbol: str, claims: list[Claim]) -> None:
        """Persist the worker's claims for a symbol (the verification input)."""

    @abstractmethod
    def write_checkpoint(self, run_id: str, result: CheckpointResult) -> None:
        """Persist one checkpoint receipt (``checkpoints/<symbol>/<lane>.json``)."""

    @abstractmethod
    def append_alarm(self, run_id: str, alarm: Any) -> None:
        """Append one alarm record to ``alarms.jsonl``."""

    @abstractmethod
    def append_escalation(self, run_id: str, record: Any) -> None:
        """Append one escalation record to ``escalations.jsonl``."""

    @abstractmethod
    def write_doc(self, run_id: str, symbol: str, markdown: str) -> None:
        """Persist the rendered markdown doc for a symbol."""

    @abstractmethod
    def load_cached_pass(
        self, symbol: str, lane: str, code_hash: str
    ) -> Optional[CheckpointResult]:
        """Return a prior PASS for symbol+lane iff its ``code_hash`` matches, else None."""


def _to_jsonable(obj: Any) -> Any:
    """Best-effort conversion of dataclasses / pydantic models / enums to plain JSON."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, Verdict):
        return obj.value
    if hasattr(obj, "model_dump"):  # pydantic BaseModel (e.g. a Claim variant)
        return obj.model_dump()
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    return str(obj)


_SAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]")


def _safe(name: str) -> str:
    """Sanitize a symbol/lane name for use as a path component."""
    return _SAFE_NAME.sub("_", name) or "_"


class LocalFileStore(Store):
    """Local-filesystem implementation of ``Store`` against ``<root>/<run_id>/``.

    Simple and synchronous: good enough for the sprint and the replay demo. ``runs/`` is
    the default root; pass another for tests.
    """

    def __init__(self, root: str | os.PathLike[str] = "runs") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # -- helpers ----------------------------------------------------------------
    def _run_dir(self, run_id: str) -> Path:
        return self.root / _safe(run_id)

    def _next_run_id(self) -> str:
        # Deterministic, dependency-free, monotonic-ish id: count existing runs.
        existing = [p.name for p in self.root.iterdir() if p.is_dir()] if self.root.exists() else []
        n = len(existing) + 1
        # Avoid collisions if a same-numbered dir already exists.
        while f"run-{n:04d}" in existing:
            n += 1
        return f"run-{n:04d}"

    def _write_json(self, path: Path, obj: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_to_jsonable(obj), indent=2), encoding="utf-8")

    def _append_jsonl(self, path: Path, obj: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(_to_jsonable(obj)) + "\n")

    # -- interface --------------------------------------------------------------
    def new_run(self, manifest: dict) -> str:
        run_id = str(manifest.get("run_id") or self._next_run_id())
        run_dir = self._run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        stamped = {"run_id": run_id, **manifest}
        self._write_json(run_dir / "manifest.json", stamped)
        return run_id

    def write_claims(self, run_id: str, symbol: str, claims: list[Claim]) -> None:
        path = self._run_dir(run_id) / "claims" / f"{_safe(symbol)}.json"
        self._write_json(path, list(claims))

    def write_checkpoint(self, run_id: str, result: CheckpointResult) -> None:
        path = (
            self._run_dir(run_id)
            / "checkpoints"
            / _safe(result.symbol)
            / f"{_safe(result.lane)}.json"
        )
        self._write_json(path, result)

    def append_alarm(self, run_id: str, alarm: Any) -> None:
        self._append_jsonl(self._run_dir(run_id) / "alarms.jsonl", alarm)

    def append_escalation(self, run_id: str, record: Any) -> None:
        self._append_jsonl(self._run_dir(run_id) / "escalations.jsonl", record)

    def write_doc(self, run_id: str, symbol: str, markdown: str) -> None:
        path = self._run_dir(run_id) / "docs" / f"{_safe(symbol)}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown, encoding="utf-8")

    def load_cached_pass(
        self, symbol: str, lane: str, code_hash: str
    ) -> Optional[CheckpointResult]:
        """Scan prior runs for a PASS receipt for symbol+lane whose hash matches.

        Returns the most recent matching PASS as a ``CheckpointResult`` (without the
        original ``Claim`` rehydrated — stored as a plain dict), else ``None``.
        """
        rel = Path("checkpoints") / _safe(symbol) / f"{_safe(lane)}.json"
        candidates = []
        if not self.root.exists():
            return None
        for run_dir in self.root.iterdir():
            cp = run_dir / rel
            if cp.is_file():
                candidates.append(cp)
        # Most recent run wins (lexicographic on run-NNNN == chronological here).
        for cp in sorted(candidates, reverse=True):
            try:
                data = json.loads(cp.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if data.get("verdict") == Verdict.PASS.value and data.get("code_hash") == code_hash:
                return CheckpointResult(
                    symbol=data["symbol"],
                    claim=data.get("claim"),
                    verdict=Verdict.PASS,
                    evidence=data.get("evidence", ""),
                    code_hash=data["code_hash"],
                    lane=data["lane"],
                    timestamp=data.get("timestamp", ""),
                    duration_ms=data.get("duration_ms", 0.0),
                )
        return None
