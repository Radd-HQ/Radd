"""Jira-style duration parsing/formatting — the module's one core invariant.

`2w 1d 4h 30m` <-> seconds. A bare number (no unit) is minutes (Jira's log-work
default). Week/day lengths are configurable (a working week, not a calendar week),
so the *seconds* are canonical and the text is just how humans enter/read them.

Pure functions: units come in as arguments (from Settings) so this stays DB- and
config-import-independent and unit-testable. Invalid input raises ValueError, which
the router surfaces as a 422.
"""

import re


class DurationError(ValueError):
    """Malformed duration text — the router/module maps this to a 422."""


SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600

# One "2h", "30m", "1d", "2w", or a bare "45" (minutes). Case-insensitive.
_UNIT_TOKEN = re.compile(r"(?P<value>\d+)(?P<unit>[wdhm])?", re.IGNORECASE)


def _unit_seconds(hours_per_day: int, days_per_week: int) -> dict[str, int]:
    day = hours_per_day * SECONDS_PER_HOUR
    return {
        "m": SECONDS_PER_MINUTE,
        "h": SECONDS_PER_HOUR,
        "d": day,
        "w": day * days_per_week,
    }


def parse_duration(text: str, *, hours_per_day: int = 8, days_per_week: int = 5) -> int:
    """`"1d 2h 30m"` -> seconds. Bare integers are minutes. Raises ValueError if empty,
    malformed, or non-positive."""
    # Collapse internal whitespace so "2h 30m" and "2h30m" parse identically.
    cleaned = re.sub(r"\s+", "", text.lower())
    if not cleaned:
        raise DurationError("duration is empty")
    units = _unit_seconds(hours_per_day, days_per_week)
    total = 0
    consumed = 0
    for match in _UNIT_TOKEN.finditer(cleaned):
        # Reject stray characters between tokens (e.g. "2h x").
        if match.start() != consumed:
            raise DurationError(f"unexpected character in duration: {text!r}")
        consumed = match.end()
        unit = (match.group("unit") or "m").lower()
        total += int(match.group("value")) * units[unit]
    if consumed != len(cleaned) or total <= 0:
        raise DurationError(f"not a valid duration: {text!r} (try '2h 30m', '1d', '90m')")
    return total


def format_duration(seconds: int, *, hours_per_day: int = 8, days_per_week: int = 5) -> str:
    """Seconds -> the largest-unit-first form, e.g. 5400 -> '1h 30m'. 0 -> '0m'.
    Negative values (an over-logged remaining) keep their magnitude: -9900 -> '-2h 45m'
    — flooring them at '0m' is how the UI once showed a nonsense "0m over"."""
    if seconds == 0:
        return "0m"
    sign = "-" if seconds < 0 else ""
    units = _unit_seconds(hours_per_day, days_per_week)
    parts: list[str] = []
    remaining = abs(seconds)
    for unit in ("w", "d", "h", "m"):
        size = units[unit]
        count, remaining = divmod(remaining, size)
        if count:
            parts.append(f"{count}{unit}")
    # Sub-minute remainders are dropped (worklogs are whole minutes at least).
    return sign + " ".join(parts) if parts else "0m"
