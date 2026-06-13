"""Sandbox tests — the riskiest component's definition of done (sessions.md Session 0).

Covers: passing assert -> ok; failing assert -> ok=False with the real traceback;
infinite loop -> timed_out; run_call return value; non-JSON-serializable return; stdout
capture; and a syntax error in module_source.
"""

import pytest

from harness.checkpoints.sandbox import run_assert, run_call

ADD_SRC = "def add(a, b):\n    return a + b\n"
SORT_REVERSED_SRC = "def sort_items(xs):\n    return sorted(xs, reverse=True)\n"


def test_passing_assert_is_ok():
    res = run_assert(ADD_SRC, "add", "assert add(2, 3) == 5")
    assert res.ok is True
    assert res.error is None
    assert res.timed_out is False
    assert res.duration_ms >= 0


def test_failing_assert_returns_real_traceback():
    res = run_assert(ADD_SRC, "add", "assert add(2, 3) == 6")
    assert res.ok is False
    assert res.timed_out is False
    assert res.error is not None
    # The real traceback, not a synthesized message.
    assert "AssertionError" in res.error
    assert "Traceback" in res.error


def test_infinite_loop_times_out():
    res = run_assert(ADD_SRC, "add", "while True:\n    pass", timeout_s=1.0)
    assert res.timed_out is True
    assert res.ok is False
    assert res.duration_ms >= 900  # roughly the timeout window


def test_run_call_returns_value():
    res = run_call(ADD_SRC, "add", args=[4, 5], kwargs={})
    assert res.ok is True
    assert res.value == 9
    assert res.error is None


def test_run_call_planted_bug_value():
    # A reversing sort_items: run_call surfaces the real (wrong-per-claim) output.
    res = run_call(SORT_REVERSED_SRC, "sort_items", args=[[3, 1, 2]], kwargs={})
    assert res.ok is True
    assert res.value == [3, 2, 1]


def test_run_call_rejects_non_json_serializable():
    src = "def f():\n    return object()\n"
    res = run_call(src, "f", args=[], kwargs={})
    assert res.ok is False
    assert res.error is not None


def test_missing_symbol_is_error():
    res = run_call(ADD_SRC, "nope", args=[], kwargs={})
    assert res.ok is False
    assert "nope" in res.error


def test_syntax_error_in_module_source():
    res = run_assert("def broken(:\n    pass\n", "broken", "assert True")
    assert res.ok is False
    assert "SyntaxError" in res.error


def test_stdout_is_captured_and_does_not_corrupt_result():
    res = run_assert(ADD_SRC, "add", "print('hello from sandbox')\nassert add(1, 1) == 2")
    assert res.ok is True
    assert "hello from sandbox" in res.stdout


def test_behavioral_namespace_has_result_args_kwargs():
    # result/args/kwargs exist in the snippet namespace per design.md §4.
    res = run_assert(ADD_SRC, "add", "assert args == [] and kwargs == {}")
    assert res.ok is True
