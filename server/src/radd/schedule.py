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
- monthly: the next wall-clock HH:MM in `tz` on the given day of the month,
  clamped to the month's last day (the 31st fires on 28 February).
- cron: the next moment matching a five-field cron expression, via croniter.

Wall-clock times are resolved through zoneinfo, so DST transitions keep the
LOCAL time stable (the UTC gap to the next run stretches/shrinks with the
offset change, as a human reading "every day at 09:00" expects).
"""

from calendar import monthrange
from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from enum import StrEnum


class ScheduleKind(StrEnum):
    """Shape of a schedule config: interval = every N minutes; daily = every day
    at HH:MM; weekly = at HH:MM on the listed weekdays (0=Mon); monthly = at
    HH:MM on a day of the month, clamped to the month's last day; cron = a
    five-field cron expression. Times are interpreted in
    `settings.scheduler_tz`."""

    INTERVAL = "interval"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CRON = "cron"


_WEEK_DAYS = 7

#: Floor on how often any schedule may fire. Lives here rather than in
#: `automations` because backups share this vocabulary and a second copy would
#: eventually disagree about what "too often" means.
MIN_INTERVAL_MINUTES = 5


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


def _next_monthly(now: datetime, tz: str, at: time, day: int) -> datetime:
    """The next `day`-of-month at `at`, strictly after now.

    CLAMPED to the month's last day: a schedule set for the 31st fires on the
    28th of February rather than skipping the month entirely. Skipping is the
    other obvious reading and it is the wrong one — "monthly on the 31st" is
    someone asking for month-end, and a maintenance ticket that silently misses
    four months a year is worse than one that arrives three days early.
    """
    local_now = _local_now(now, tz)
    year, month = local_now.year, local_now.month
    for _ in range(_MONTHS_AHEAD):
        last_day = monthrange(year, month)[1]
        candidate = datetime.combine(
            date(year, month, min(day, last_day)), at, tzinfo=ZoneInfo(tz)
        )
        if candidate > local_now:
            return _to_naive_utc(candidate)
        month, year = (1, year + 1) if month == 12 else (month + 1, year)
    raise ValueError("no month matches the schedule")  # unreachable when validated


def _next_cron(now: datetime, tz: str, expression: str) -> datetime:
    """The next moment matching a cron expression, in `tz`.

    Delegated to croniter rather than parsed here. Cron's day-of-month and
    day-of-week fields OR together when both are restricted — a rule nobody
    remembers and every hand-rolled parser gets wrong for years before anyone
    notices. It is a specified standard; taking the small dependency is the
    cheaper correctness.
    """
    from croniter import croniter

    return _to_naive_utc(croniter(expression, _local_now(now, tz)).get_next(datetime))


def next_run(cfg: Mapping[str, Any], now: datetime, tz: str) -> datetime:
    """Naive-UTC moment of the next occurrence strictly after naive-UTC `now`."""
    kind = ScheduleKind(cfg["kind"])
    if kind is ScheduleKind.INTERVAL:
        return now + timedelta(minutes=int(cfg["minutes"]))
    if kind is ScheduleKind.CRON:
        return _next_cron(now, tz, str(cfg["expression"]))
    at = parse_hh_mm(cfg["time"])
    if kind is ScheduleKind.DAILY:
        return _next_wall_clock(now, tz, at, weekdays=None)
    if kind is ScheduleKind.MONTHLY:
        return _next_monthly(now, tz, at, int(cfg["day"]))
    return _next_wall_clock(now, tz, at, weekdays=frozenset(int(d) for d in cfg["weekdays"]))


def cron_shortest_gap(expression: str, tz: str) -> timedelta:
    """The smallest gap between consecutive runs of a cron expression.

    The interval floor cannot be read off a cron config the way it is read off
    `minutes` — `* * * * *` names no number at all — so it is MEASURED. Sampling
    a handful of consecutive occurrences is enough: anything firing too often
    does so relentlessly, and a schedule whose only tight pair is far in the
    future is not what the floor exists to stop.
    """
    from croniter import croniter

    itr = croniter(expression, datetime.now(ZoneInfo(tz)))
    times = [itr.get_next(datetime) for _ in range(_CRON_SAMPLES)]
    return min(b - a for a, b in zip(times, times[1:]))


def validate_config(cfg: Mapping[str, Any]) -> None:
    """Shape rules for a stored schedule config; raises ValueError.

    Here rather than in each caller's pydantic model. `automations` and `backup`
    each had their own copy of these checks, already subtly different — one
    accepted a stray `weekdays` on a daily schedule that the other rejected —
    and adding two kinds to two copies is how that becomes three differences.
    """
    try:
        kind = ScheduleKind(str(cfg.get("kind")))
    except ValueError:
        raise ValueError(f"unknown schedule kind {cfg.get('kind')!r}") from None

    # FALSY counts as absent, not as present-and-wrong. Stored configs carry
    # `weekdays: []` on daily schedules — the backup form has always written it
    # that way — and treating an empty list as "you supplied weekdays" would
    # reject every schedule already in the database.
    present = {
        key
        for key in ("minutes", "time", "weekdays", "day", "expression")
        if cfg.get(key)
    }
    allowed = _FIELDS_BY_KIND[kind]
    if stray := present - allowed:
        raise ValueError(
            f"a {kind.value} schedule does not take {', '.join(sorted(stray))}"
        )
    for required in _REQUIRED_BY_KIND[kind]:
        if cfg.get(required) is None:
            raise ValueError(f"a {kind.value} schedule needs `{required}`")

    if kind is ScheduleKind.INTERVAL:
        if int(cfg["minutes"]) < MIN_INTERVAL_MINUTES:
            raise ValueError(f"an interval schedule runs at most every {MIN_INTERVAL_MINUTES} minutes")
        return

    if kind is ScheduleKind.CRON:
        expression = str(cfg["expression"]).strip()
        from croniter import croniter

        if not croniter.is_valid(expression):
            raise ValueError(f"{expression!r} is not a valid cron expression")
        # The floor, measured rather than declared — see `cron_shortest_gap`.
        if cron_shortest_gap(expression, "UTC") < timedelta(minutes=MIN_INTERVAL_MINUTES):
            raise ValueError(
                f"that expression fires more often than every {MIN_INTERVAL_MINUTES} minutes"
            )
        return

    try:
        parse_hh_mm(str(cfg["time"]))
    except ValueError:
        raise ValueError(f"invalid time {cfg['time']!r} — expected HH:MM") from None

    if kind is ScheduleKind.MONTHLY:
        day = int(cfg["day"])
        if day < 1 or day > 31:
            raise ValueError("the day of the month must be 1 to 31")
        return

    if kind is ScheduleKind.WEEKLY:
        weekdays = [int(d) for d in cfg["weekdays"]]
        if not weekdays:
            raise ValueError("a weekly schedule needs at least one weekday (0=Mon)")
        if any(day < 0 or day > 6 for day in weekdays):
            raise ValueError("weekdays are 0 (Mon) to 6 (Sun)")
        if len(set(weekdays)) != len(weekdays):
            raise ValueError("weekdays must not repeat")


#: How many months ahead `_next_monthly` will look. Thirteen so that a schedule
#: on the 29th, 30th or 31st always finds a month — the clamp means it never has
#: to, but a bounded loop beats a `while True` that a bad config could hang on.
_MONTHS_AHEAD = 13
#: Consecutive occurrences sampled when measuring a cron expression's cadence.
_CRON_SAMPLES = 5

_FIELDS_BY_KIND: dict[ScheduleKind, set[str]] = {
    ScheduleKind.INTERVAL: {"minutes"},
    ScheduleKind.DAILY: {"time"},
    ScheduleKind.WEEKLY: {"time", "weekdays"},
    ScheduleKind.MONTHLY: {"time", "day"},
    ScheduleKind.CRON: {"expression"},
}
_REQUIRED_BY_KIND: dict[ScheduleKind, set[str]] = {
    ScheduleKind.INTERVAL: {"minutes"},
    ScheduleKind.DAILY: {"time"},
    ScheduleKind.WEEKLY: {"time", "weekdays"},
    ScheduleKind.MONTHLY: {"time", "day"},
    ScheduleKind.CRON: {"expression"},
}
