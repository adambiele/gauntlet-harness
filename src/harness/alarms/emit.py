"""Alarm emit helpers — build, persist, and stream alarms (design.md §7).

Three entry points:

* ``make_alarm`` — construct a populated :class:`~harness.alarms.types.Alarm` from an
  :class:`~harness.alarms.types.AlarmType` registry entry, copying ``severity`` and
  ``recommended_action`` so each persisted record is self-describing.
* ``emit`` — append the alarm to the run's ``alarms.jsonl`` via a
  :class:`~harness.persistence.store.Store` and return it (fluent).
* ``to_event`` — convert an ``Alarm`` to an :class:`~harness.adapters.events.AlarmEvent`
  for SSE streaming to the dashboard.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from harness.adapters.events import AlarmEvent
from harness.alarms.types import Alarm, AlarmType
from harness.persistence.store import Store

__all__ = ["make_alarm", "emit", "to_event"]


def make_alarm(
    alarm_type: AlarmType,
    symbol: str,
    message: str,
    claim_ref: Optional[str] = None,
) -> Alarm:
    """Build a populated :class:`Alarm` from a registry entry.

    ``severity`` and ``recommended_action`` are copied from *alarm_type* so that each
    record stored in ``alarms.jsonl`` is fully self-describing — readers don't need to
    look up the registry.  The ISO timestamp is stamped in UTC at construction time.

    Args:
        alarm_type: A registry constant such as ``PHANTOM_API`` or ``EXAMPLE_FAILED``.
        symbol:     The target symbol that triggered the alarm.
        message:    Human-readable description of the specific violation.
        claim_ref:  Optional reference string pointing at the offending claim (e.g.
                    the claim ``type`` or a short prose excerpt).

    Returns:
        A fully-populated :class:`Alarm` instance ready to be passed to :func:`emit`.
    """
    return Alarm(
        type=alarm_type.name,
        severity=alarm_type.severity,
        symbol=symbol,
        claim_ref=claim_ref,
        message=message,
        recommended_action=alarm_type.recommended_action,
        timestamp=datetime.now(tz=timezone.utc).isoformat(),
    )


def emit(store: Store, run_id: str, alarm: Alarm) -> Alarm:
    """Append *alarm* to the run's ``alarms.jsonl`` and return it.

    Delegates to :meth:`~harness.persistence.store.Store.append_alarm` so the
    persistence layer handles serialisation.  The alarm is returned unchanged so callers
    can write ``my_alarm = emit(store, run_id, my_alarm)`` without losing the reference.

    Args:
        store:  The active :class:`~harness.persistence.store.Store` for this run.
        run_id: Identifies which run's ``alarms.jsonl`` to append to.
        alarm:  The :class:`Alarm` to persist.

    Returns:
        The same *alarm* instance, unchanged.
    """
    store.append_alarm(run_id, alarm)
    return alarm


def to_event(alarm: Alarm) -> AlarmEvent:
    """Convert an :class:`Alarm` to an :class:`~harness.adapters.events.AlarmEvent`.

    ``AlarmEvent`` uses the field name ``alarm_type`` (the SSE wire name) whereas
    :class:`Alarm` uses ``type`` (the registry name).  All other fields are mirrored
    field-for-field.

    Args:
        alarm: A raised alarm instance.

    Returns:
        An :class:`AlarmEvent` suitable for passing to
        :func:`~harness.adapters.events.to_sse`.
    """
    return AlarmEvent(
        alarm_type=alarm.type,
        severity=alarm.severity,
        symbol=alarm.symbol,
        claim_ref=alarm.claim_ref,
        message=alarm.message,
        recommended_action=alarm.recommended_action,
        timestamp=alarm.timestamp,
    )
