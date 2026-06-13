"""Alarms pillar — structured, named alarms with severity + action (design.md §7).

Session 0 ships the types + registry (``types.py``).
Session A4 adds the emit helpers (``emit.py``): ``make_alarm``, ``emit``, ``to_event``.

Note: ``emit.py`` is intentionally **not** re-exported here to avoid a circular import
with ``harness.adapters.events`` (which itself imports ``harness.alarms.types``).
Import emit helpers directly::

    from harness.alarms.emit import make_alarm, emit, to_event
"""

from harness.alarms.types import REGISTRY, Alarm, AlarmType, Severity

__all__ = ["Severity", "AlarmType", "REGISTRY", "Alarm"]
