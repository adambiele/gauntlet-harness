"""Alarms pillar — structured, named alarms with severity + action (design.md §7).

Session 0 ships only the types + registry. Emit logic (``emit.py``) is Session A4.
"""

from harness.alarms.types import REGISTRY, Alarm, AlarmType, Severity

__all__ = ["Severity", "AlarmType", "REGISTRY", "Alarm"]
