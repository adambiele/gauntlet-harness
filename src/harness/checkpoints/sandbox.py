"""Subprocess sandbox — the actual trust boundary for model-generated code.

This is the riskiest component (design.md §4, §4b): it runs untrusted, model-generated
code in a **separate interpreter** with a wall-clock timeout, capturing the return value
(``run_call``) or an assert outcome (``run_assert``), plus any stdout and the real
traceback on failure.

Why a subprocess and not an AST allowlist or RestrictedPython: AST allowlists are
escapable in Python and RestrictedPython constrains otherwise-valid asserts. A separate
process with a timeout and a throwaway cwd is the boundary we actually rely on; the
guardrail-layer AST allowlist (A3) is a declared fast-reject in front of it, not the
boundary.

Protocol: the parent spawns ``sys.executable -c <runner>``, hands a JSON payload on
stdin, and the child writes ``SENTINEL + json.dumps(result)`` to stdout. User-code stdout
is redirected into the result so it never corrupts the protocol. A timeout kills the
child and yields ``timed_out=True``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Optional

__all__ = ["SandboxResult", "run_call", "run_assert"]

# Marks the start of the machine-readable result on the child's stdout. Anything the
# user code prints is captured separately (redirected) and reported in ``stdout``, so the
# only thing on real stdout after this marker is our JSON.
_SENTINEL = "<<<<HARNESS_SANDBOX_RESULT_a9f3>>>>"


@dataclass
class SandboxResult:
    """Outcome of one sandboxed execution.

    * ``ok`` — True iff the call returned / the assert passed with no exception.
    * ``value`` — the JSON-serializable return value (``run_call`` only; else ``None``).
    * ``error`` — the real traceback string on failure, else ``None``.
    * ``stdout`` — whatever the executed code printed.
    * ``timed_out`` — True iff the child was killed by the wall-clock timeout.
    * ``duration_ms`` — wall-clock time the child ran.
    """

    ok: bool
    value: Any
    error: Optional[str]
    stdout: str
    timed_out: bool
    duration_ms: float


# The child program. Kept dependency-free (stdlib only) and self-contained so it can run
# under a bare ``python -c``. Reads one JSON payload from stdin, writes one result.
_RUNNER = r'''
import sys, json, io, contextlib, traceback

SENTINEL = "<<<<HARNESS_SANDBOX_RESULT_a9f3>>>>"

def main():
    payload = json.load(sys.stdin)
    mode = payload["mode"]
    module_source = payload["module_source"]
    symbol_name = payload["symbol_name"]
    args = payload.get("args") or []
    kwargs = payload.get("kwargs") or {}
    snippet = payload.get("snippet")

    captured = io.StringIO()
    result = {"ok": False, "value": None, "error": None}
    with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(captured):
        try:
            ns = {}
            exec(compile(module_source, "<module_source>", "exec"), ns)
            if symbol_name not in ns:
                raise NameError(
                    "symbol %r is not defined by module_source" % (symbol_name,)
                )
            symbol = ns[symbol_name]

            if mode == "call":
                value = symbol(*args, **kwargs)
                # Enforce the JSON-serializable contract here so a non-serializable
                # return is reported as a clean failure, not a parent-side crash.
                json.dumps(value)
                result["value"] = value
                result["ok"] = True
            elif mode == "assert":
                # Namespace per design.md §4: the symbol by name, plus result/args/kwargs.
                # ``result`` is precomputed best-effort; if the symbol can't be called
                # with the given (often empty) args, the snippet is expected to call it
                # itself, so a precompute failure must not poison the assert.
                try:
                    precomputed = symbol(*args, **kwargs)
                except BaseException:
                    precomputed = None
                local_ns = dict(ns)
                local_ns[symbol_name] = symbol
                local_ns["result"] = precomputed
                local_ns["args"] = args
                local_ns["kwargs"] = kwargs
                exec(compile(snippet, "<snippet>", "exec"), local_ns)
                result["ok"] = True
            else:
                raise ValueError("unknown mode %r" % (mode,))
        except BaseException:
            result["error"] = traceback.format_exc()
            result["ok"] = False

    result["stdout"] = captured.getvalue()
    sys.__stdout__.write(SENTINEL + json.dumps(result))
    sys.__stdout__.flush()

main()
'''


def _execute(payload: dict, timeout_s: float) -> SandboxResult:
    """Spawn the child, feed it ``payload``, and parse its result."""
    cwd = tempfile.mkdtemp(prefix="harness-sandbox-")
    start = time.monotonic()
    try:
        proc = subprocess.run(
            [sys.executable, "-c", _RUNNER],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=cwd,
            # Minimal, isolated environment: no inherited PYTHON* knobs, no network creds.
            env={"PATH": os.environ.get("PATH", "")},
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = (time.monotonic() - start) * 1000
        partial = exc.stdout or ""
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", "replace")
        stdout, _ = _split_sentinel(partial)
        return SandboxResult(
            ok=False,
            value=None,
            error=f"execution timed out after {timeout_s:g}s",
            stdout=stdout,
            timed_out=True,
            duration_ms=duration_ms,
        )
    finally:
        shutil.rmtree(cwd, ignore_errors=True)

    duration_ms = (time.monotonic() - start) * 1000
    pre, encoded = _split_sentinel(proc.stdout)

    if encoded is None:
        # Child died before writing a result (hard crash, killed, interpreter error).
        detail = (proc.stderr or "").strip() or "no result emitted by sandbox child"
        return SandboxResult(
            ok=False,
            value=None,
            error=f"sandbox child produced no result: {detail}",
            stdout=pre,
            timed_out=False,
            duration_ms=duration_ms,
        )

    try:
        data = json.loads(encoded)
    except json.JSONDecodeError as exc:
        return SandboxResult(
            ok=False,
            value=None,
            error=f"could not decode sandbox result: {exc}",
            stdout=pre,
            timed_out=False,
            duration_ms=duration_ms,
        )

    return SandboxResult(
        ok=bool(data.get("ok")),
        value=data.get("value"),
        error=data.get("error"),
        stdout=data.get("stdout", ""),
        timed_out=False,
        duration_ms=duration_ms,
    )


def _split_sentinel(raw: str) -> tuple[str, Optional[str]]:
    """Split child stdout into (anything-before-sentinel, encoded-result-or-None)."""
    idx = raw.find(_SENTINEL)
    if idx == -1:
        return raw, None
    return raw[:idx], raw[idx + len(_SENTINEL):]


def run_call(
    module_source: str,
    symbol_name: str,
    args: list,
    kwargs: dict,
    timeout_s: float = 5.0,
) -> SandboxResult:
    """Define ``symbol_name`` from ``module_source`` and call it with ``args``/``kwargs``.

    The return value must be JSON-serializable (it crosses the process boundary as JSON);
    a non-serializable return is reported as ``ok=False`` with the offending traceback.
    On success ``ok=True`` and ``value`` holds the (round-tripped) return value.
    """
    payload = {
        "mode": "call",
        "module_source": module_source,
        "symbol_name": symbol_name,
        "args": list(args),
        "kwargs": dict(kwargs),
    }
    return _execute(payload, timeout_s)


def run_assert(
    module_source: str,
    symbol_name: str,
    snippet: str,
    timeout_s: float = 5.0,
) -> SandboxResult:
    """Run ``snippet`` against the symbol defined by ``module_source``.

    The snippet executes with ``symbol_name`` (the symbol), ``result`` (a best-effort
    ``symbol()`` value), ``args`` and ``kwargs`` in scope. A passing assert → ``ok=True``;
    any ``AssertionError`` / exception → ``ok=False`` with the real traceback in ``error``.
    """
    payload = {
        "mode": "assert",
        "module_source": module_source,
        "symbol_name": symbol_name,
        "snippet": snippet,
    }
    return _execute(payload, timeout_s)
