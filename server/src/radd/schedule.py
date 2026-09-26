"""Pure next-occurrence math shared by automations and backups (spec 99) — one copy of
DST-correct wall-clock arithmetic. Unit-tested in tests/test_scheduled_automations.py.

`next_run(cfg, now, tz)` takes a stored config ({kind, minutes | time, weekdays | day |
expression}), a NAIVE-UTC `now` and an IANA zone, and returns the naive-UTC moment of the
next occurrence STRICTLY after now. Interval adds `minutes` to `now` (the scheduler calls
it right after firing); wall-clock kinds go through zoneinfo, so DST keeps the LOCAL time
stable; monthly clamps to the month's last day; cron is croniter's.
"""

from calendar import monthrange
from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from enum import StrEnum


class ScheduleKind(StrEnum):
    """A schedule config's shape; weekdays are 0=Mon, times are in `settings.scheduler_tz`."""

    INTERVAL = "interval"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CRON = "cron"


_WEEK_DAYS = 7

#: Floor on how often any schedule may fire (one value for automations and backups).
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
    """The next `day`-of-month at `at`, strictly after now — CLAMPED to the month's last
    day, not skipped: "monthly on the 31st" means month-end."""
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
    """The next moment matching a cron expression, in `tz`. croniter, not a hand-rolled
    parser: day-of-month and day-of-week OR together when both are restricted."""
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
    """The smallest gap between a few consecutive runs — MEASURED, since `* * * * *` names
    no number; anything firing too often does so relentlessly, so a sample suffices."""
    from croniter import croniter

    itr = croniter(expression, datetime.now(ZoneInfo(tz)))
    times = [itr.get_next(datetime) for _ in range(_CRON_SAMPLES)]
    return min(b - a for a, b in zip(times, times[1:]))


def validate_config(cfg: Mapping[str, Any]) -> None:
    """Shape rules for a stored schedule config, one copy for every caller; raises ValueError."""
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
    fields = _FIELDS_BY_KIND[kind]
    if stray := present - fields:
        raise ValueError(
            f"a {kind.value} schedule does not take {', '.join(sorted(stray))}"
        )
    for required in fields:
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


#: Bound on `_next_monthly`'s loop (the clamp always matches sooner; no `while True`).
_MONTHS_AHEAD = 13
#: Consecutive occurrences sampled when measuring a cron expression's cadence.
_CRON_SAMPLES = 5

#: Each kind's fields: all of them required, no others allowed.
_FIELDS_BY_KIND: dict[ScheduleKind, set[str]] = {
    ScheduleKind.INTERVAL: {"minutes"},
    ScheduleKind.DAILY: {"time"},
    ScheduleKind.WEEKLY: {"time", "weekdays"},
    ScheduleKind.MONTHLY: {"time", "day"},
    ScheduleKind.CRON: {"expression"},
}
