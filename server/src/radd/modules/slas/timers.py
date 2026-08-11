"""Pure SLA timer math (spec 30) — unit-tested in tests/test_sla.py.

The clock runs from the item's creation, PAUSES while the item sits in one of
the policy's pause states, and stops when the target is met. The deadline is
the moment accumulated ACTIVE (non-paused) time reaches the target — walking
the pause intervals directly, so pausing before the deadline pushes it out
exactly, with no fixpoint iteration.

Everything here is a function of its arguments — no database, no registry, no
clock beyond the `now` it is handed. Non-working days arrive as a work-week set
and (RADD-1031) a set of calendar DATES; whoever knows which dates those are
resolves them elsewhere (`slas/calendar.py`).
"""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, datetime, timedelta


WEEKDAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def parse_work_week(value: str) -> frozenset[int]:
    """`"mon,tue,fri"` → weekday ints (Mon=0). Unknown names are ignored; an
    empty/garbage value falls back to Mon–Fri (a zero-day week would make every
    work-week timer float forever)."""
    days = frozenset(
        WEEKDAY_NAMES.index(part.strip().lower())
        for part in value.split(",")
        if part.strip().lower() in WEEKDAY_NAMES
    )
    return days or frozenset(range(5))


def non_working_pauses(
    start: datetime,
    end: datetime,
    working_days: frozenset[int],
    non_working_dates: Collection[date] = (),
) -> list[tuple[datetime, datetime | None]]:
    """Midnight-to-midnight pause intervals for every non-working day between
    start and end (spec 35) — merged into a policy's state pauses so the SLA
    clock skips weekends. Naive UTC days, matching event timestamps.

    `non_working_dates` (RADD-1031) are individual CALENDAR DATES that are
    non-working regardless of weekday — a studio holiday falling on a Tuesday.
    Passed in as plain dates rather than looked up here on purpose: this module
    is pure timer math and must stay computable without a database, so who
    decides a date is a holiday is the caller's business (`slas/calendar.py`
    resolves them through the kernel socket). An empty set is exactly the
    pre-RADD-1031 behaviour.
    """
    holidays = frozenset(non_working_dates)
    pauses: list[tuple[datetime, datetime | None]] = []
    day = datetime(start.year, start.month, start.day)
    while day <= end:
        if day.weekday() not in working_days or day.date() in holidays:
            pauses.append((day, day + timedelta(days=1)))
        day += timedelta(days=1)
    return pauses


def business_hours_pauses(
    start: datetime,
    end: datetime,
    start_minute: int,
    end_minute: int,
    working_days: frozenset[int],
) -> list[tuple[datetime, datetime | None]]:
    """Daily business-hours window (spec 63): on each WORKING day between start
    and end, pause [midnight, window-open) and [window-close, next midnight) so
    active time only accrues inside [open, close). Non-working days get nothing
    here — pass `working_days=frozenset(range(7))` to window every day, or merge
    `non_working_pauses` for whole-day weekend pauses (merge_intervals coalesces
    the adjacent intervals either way). Naive UTC, like every SLA timestamp."""
    pauses: list[tuple[datetime, datetime | None]] = []
    day = datetime(start.year, start.month, start.day)
    while day <= end:
        if day.weekday() in working_days:
            if start_minute > 0:
                pauses.append((day, day + timedelta(minutes=start_minute)))
            pauses.append((day + timedelta(minutes=end_minute), day + timedelta(days=1)))
        day += timedelta(days=1)
    return pauses


@dataclass(frozen=True)
class TimerStatus:
    due_at: datetime | None  # None = currently paused with the target unreached
    met_at: datetime | None
    breached: bool
    paused: bool
    remaining_seconds: float | None  # None once met/breached or while paused


def merge_intervals(
    intervals: list[tuple[datetime, datetime | None]],
) -> list[tuple[datetime, datetime | None]]:
    """Sort + coalesce overlapping/adjacent [start, end) pauses; end None = open."""
    merged: list[tuple[datetime, datetime | None]] = []
    for start, end in sorted(intervals, key=lambda pair: pair[0]):
        if merged:
            last_start, last_end = merged[-1]
            if last_end is None:
                break  # an open pause swallows everything after it
            if start <= last_end:
                merged[-1] = (last_start, None if end is None else max(last_end, end))
                continue
        merged.append((start, end))
    return merged


def deadline(
    started_at: datetime,
    target_seconds: float,
    pauses: list[tuple[datetime, datetime | None]],
    now: datetime,
) -> datetime | None:
    """When accumulated active time reaches the target. None = currently inside
    an open pause with the target not yet reached (the deadline floats)."""
    active = 0.0
    cursor = started_at
    for pause_start, pause_end in merge_intervals(pauses):
        if pause_end is not None and pause_end <= cursor:
            continue  # pause fully before the clock started
        span_end = max(pause_start, cursor)
        span = (span_end - cursor).total_seconds()
        if active + span >= target_seconds:
            return cursor + timedelta(seconds=target_seconds - active)
        active += span
        if pause_end is None:
            # Open-ended pause: if the target wasn't reached before it, it floats —
            # unless the pause started before `now`... it's still open, so floats.
            return None
        cursor = max(cursor, pause_end)
    return cursor + timedelta(seconds=target_seconds - active)


def in_pause(pauses: list[tuple[datetime, datetime | None]], now: datetime) -> bool:
    return any(
        start <= now and (end is None or now < end) for start, end in merge_intervals(pauses)
    )


def evaluate(
    *,
    started_at: datetime,
    target_seconds: float,
    pauses: list[tuple[datetime, datetime | None]],
    met_at: datetime | None,
    now: datetime,
) -> TimerStatus:
    """One timer's full status. Met late still reads `breached=True` (it records
    that the target was missed, even though the clock has stopped)."""
    horizon = met_at or now
    due = deadline(started_at, target_seconds, pauses, horizon)
    if met_at is not None:
        return TimerStatus(
            due_at=due,
            met_at=met_at,
            breached=due is not None and met_at > due,
            paused=False,
            remaining_seconds=None,
        )
    paused = in_pause(pauses, now)
    breached = due is not None and now > due
    remaining = None
    if not breached and not paused and due is not None:
        remaining = (due - now).total_seconds()
    return TimerStatus(
        due_at=due, met_at=None, breached=breached, paused=paused, remaining_seconds=remaining
    )
