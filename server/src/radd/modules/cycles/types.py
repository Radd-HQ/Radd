import re
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from enum import StrEnum


class CycleStatus(StrEnum):
    """DERIVED (never stored) from the cycle's dates against a caller-supplied `today` —
    plus the explicit `completed_at` close marker (sprint completed mid-window)."""

    DRAFT = "draft"  # start_date or end_date unset — a staging area; never active
    UPCOMING = "upcoming"  # today < start_date
    ACTIVE = "active"  # start_date <= today <= end_date
    COMPLETED = "completed"  # today > end_date, OR explicitly closed (completed_at)


def cycle_status(
    start_date: date | None,
    end_date: date | None,
    today: date,
    completed_at: datetime | None = None,
) -> CycleStatus:
    """Pure derivation — `today` is injected at the service boundary so it stays DB-independent.

    An explicit close (`completed_at`, the "Complete sprint" action) wins over the
    dates. Otherwise: a cycle missing either date is a DRAFT (staging) cycle — never
    active, off the roadmap/velocity/burnup until it is scheduled (given both dates)."""
    if completed_at is not None:
        return CycleStatus.COMPLETED
    if start_date is None or end_date is None:
        return CycleStatus.DRAFT
    if today < start_date:
        return CycleStatus.UPCOMING
    if today > end_date:
        return CycleStatus.COMPLETED
    return CycleStatus.ACTIVE


# Trailing integer in a cycle name — how a cycle joins its SERIES ("PIPE - 115" and
# "PIPE-114" both belong to label "PIPE"; separators are cosmetic).
_NUMBERED_NAME_RE = re.compile(r"^(?P<label>.*?)[\s\-–—_]*(?P<number>\d+)\s*$")


def parse_cycle_name(name: str) -> tuple[str, int] | None:
    """("PIPE - 115") → ("PIPE", 115); None when the name carries no trailing
    number (a one-off cycle, no series)."""
    match = _NUMBERED_NAME_RE.match(name)
    if not match or not match.group("label"):
        return None
    return match.group("label"), int(match.group("number"))


def cycle_label(name: str) -> str | None:
    """The series label of a numbered cycle name ("PIPE - 115" → "PIPE")."""
    parsed = parse_cycle_name(name)
    return parsed[0] if parsed else None


def same_label(a: str | None, b: str | None) -> bool:
    """Series membership comparison — case-insensitive, None never matches."""
    return a is not None and b is not None and a.casefold() == b.casefold()


def cycle_name(label: str, number: int) -> str:
    """Canonical generated name for a series cycle (matches the studio convention)."""
    return f"{label} - {number}"


def series_draft_names(
    existing_names: Iterable[str], label: str, next_number: int, count: int
) -> tuple[list[str], int]:
    """The next `count` draft names for a series, skipping numbers whose name already
    exists (imports can hold numbers past `next_number`). Returns (names, the
    next_number to store back on the series). Pure — tested."""
    taken = {name.casefold() for name in existing_names}
    names: list[str] = []
    number = next_number
    while len(names) < count:
        candidate = cycle_name(label, number)
        if candidate.casefold() not in taken:
            names.append(candidate)
            taken.add(candidate.casefold())
        number += 1
    return names, number


def next_weekday_on_or_after(day: date, weekday: int) -> date:
    """The first `weekday` (Python convention, 0=Monday) on or after `day`."""
    return day + timedelta(days=(weekday - day.weekday()) % 7)


def series_windows(
    latest_end: date | None,
    today: date,
    weekday: int,
    duration_days: int,
    count: int,
) -> list[tuple[date, date]]:
    """`count` scheduled (start, end) windows for a series cadence, chained after the
    label's latest scheduled cycle (or from today when none / the chain is stale).
    Each start snaps to the configured weekday; a 14-day Monday cycle chains
    back-to-back, an unaligned duration leaves a gap until the next weekday. Pure."""
    anchor = today if latest_end is None or latest_end < today else latest_end + timedelta(days=1)
    windows: list[tuple[date, date]] = []
    for _ in range(count):
        start = next_weekday_on_or_after(anchor, weekday)
        end = start + timedelta(days=duration_days - 1)
        windows.append((start, end))
        anchor = end + timedelta(days=1)
    return windows


class CycleEvent(StrEnum):
    CREATED = "cycle.created"
    UPDATED = "cycle.updated"
    DELETED = "cycle.deleted"
    COMPLETED = "cycle.completed"


class SeriesEvent(StrEnum):
    CREATED = "cycle_series.created"
    UPDATED = "cycle_series.updated"
    DELETED = "cycle_series.deleted"


class CycleEntity(StrEnum):
    CYCLE = "cycle"
    SERIES = "cycle_series"
