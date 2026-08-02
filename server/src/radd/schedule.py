"""Pure next-occurrence math — no I/O, a core util beside `worker.py`/`smtp.py`.

Written for scheduled automation rules (spec 69) and promoted here by spec 99,
when backups needed the same thing: rule 1 forbids importing another module's
internals, and a second copy of DST-correct wall-clock arithmetic would drift.
`automations` and `backup` now share this one. Unit-tested in
tests/test_scheduled_automations.py.

`next_run(cfg, now, tz)` takes a stored schedule config ({kind, minutes|time,
weekdays} — see automations.schemas.ScheduleConfig), a NAIVE-UTC `now`, and an
IANA timezone name (`settings.scheduler_tz`), and returns the naive-UTC moment
of the next occurrence STRICTLY after now:

- interval: now + minutes (the caller anchors on last_run/now — the scheduler
  calls this right after firing, so runs stay one interval apart).
- daily: the next wall-clock HH:MM in `tz` after now.
- weekly: the next wall-clock HH:MM in `tz` on one of the listed weekdays
  (0=Mon) after now.

Wall-clock times are resolved through zoneinfo, so DST transitions keep the
LOCAL time stable (the UTC gap to the next run stretches/shrinks with the
offset change, as a human reading "every day at 09:00" expects).
"""

from collections.abc import Mapping
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from enum import StrEnum


class ScheduleKind(StrEnum):
    """Shape of a schedule config: interval = every N minutes; daily = every day
    at HH:MM; weekly = at HH:MM on the listed weekdays (0=Mon). Times are
    interpreted in `settings.scheduler_tz`."""

    INTERVAL = "interval"
    DAILY = "daily"
    WEEKLY = "weekly"

_WEEK_DAYS = 7


def parse_hh_mm(value: str) -> time:
    """'HH:MM' -> time. Raises ValueError on garbage (validated on write)."""
    hours, minutes = value.split(":")
    parsed = time(hour=int(hours), minute=int(minutes))
    return parsed


def _local_now(now: datetime, tz: str) -> datetime:
    return now.replace(tzinfo=UTC).astimezone(ZoneInfo(tz))


def _to_naive_utc(local: datetime) -> datetime:
    return local.astimezone(UTC).replace(tzinfo=None)


def _next_wall_clock(
    now: datetime, tz: str, at: time, weekdays: frozenset[int] | None
) -> datetime:
    """The next occurrence of `at` (local wall clock in `tz`), strictly after
    `now`, restricted to `weekdays` (Mon=0) when given."""
    local_now = _local_now(now, tz)
    for offset in range(_WEEK_DAYS + 1):
        day = (local_now + timedelta(days=offset)).date()
        if weekdays is not None and day.weekday() not in weekdays:
            continue
        candidate = datetime.combine(day, at, tzinfo=ZoneInfo(tz))
        if candidate > local_now:
            return _to_naive_utc(candidate)
    raise ValueError("no weekday matches the schedule")  # unreachable when validated


def next_run(cfg: Mapping[str, Any], now: datetime, tz: str) -> datetime:
    """Naive-UTC moment of the next occurrence strictly after naive-UTC `now`."""
    kind = ScheduleKind(cfg["kind"])
    if kind is ScheduleKind.INTERVAL:
        return now + timedelta(minutes=int(cfg["minutes"]))
    at = parse_hh_mm(cfg["time"])
    if kind is ScheduleKind.DAILY:
        return _next_wall_clock(now, tz, at, weekdays=None)
    return _next_wall_clock(now, tz, at, weekdays=frozenset(int(d) for d in cfg["weekdays"]))
