"""Checkpoints pillar — explicit pass/fail, routed by claim type.

Session 0 ships only ``sandbox.py`` (the riskiest piece). Session A2 adds the four
checkpoint lanes (signature, example, behavioral) and the runner that routes by
claim type.
"""

from harness.checkpoints.behavioral import check_behavioral
from harness.checkpoints.example import check_example
from harness.checkpoints.runner import verify
from harness.checkpoints.sandbox import SandboxResult, run_assert, run_call
from harness.checkpoints.signature import check_signature

__all__ = [
    "SandboxResult",
    "run_call",
    "run_assert",
    "check_signature",
    "check_example",
    "check_behavioral",
    "verify",
]
