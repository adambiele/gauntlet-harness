"""Checkpoints pillar — explicit pass/fail, routed by claim type.

Session 0 ships only ``sandbox.py`` (the riskiest piece). The signature/example/
behavioral lanes and the router are Session A2.
"""

from harness.checkpoints.sandbox import SandboxResult, run_assert, run_call

__all__ = ["SandboxResult", "run_call", "run_assert"]
