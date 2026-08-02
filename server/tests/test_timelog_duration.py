"""Core invariant: Jira-style duration parsing/formatting (spec 22).

Worklog + estimate seconds are derived from user-typed text here, so this is the
one piece of the timelogging module that earns a unit test (dev rule 4).
"""

import pytest

from radd.modules.timelogging.duration import (
    DurationError,
    format_duration,
    parse_duration,
)

# Defaults: 8h working day, 5d working week.
HOUR = 3600
DAY = 8 * HOUR
WEEK = 5 * DAY


@pytest.mark.parametrize(
    "text,seconds",
    [
        ("30m", 1800),
        ("2h", 2 * HOUR),
        ("2h 30m", 2 * HOUR + 1800),
        ("1d", DAY),
        ("1d 4h", DAY + 4 * HOUR),
        ("2w", 2 * WEEK),
        ("1w 1d 1h 1m", WEEK + DAY + HOUR + 60),
        ("45", 45 * 60),  # bare number = minutes
        ("  3H  ", 3 * HOUR),  # case-insensitive + surrounding space
    ],
)
def test_parse_duration(text, seconds):
    assert parse_duration(text) == seconds


@pytest.mark.parametrize("text", ["", "   ", "2x", "h", "2h x", "-5m", "0m", "abc"])
def test_parse_duration_rejects_garbage(text):
    with pytest.raises(DurationError):
        parse_duration(text)


@pytest.mark.parametrize(
    "seconds,text",
    [
        (0, "0m"),
        (1800, "30m"),
        (2 * HOUR + 1800, "2h 30m"),
        (DAY, "1d"),
        (DAY + 4 * HOUR, "1d 4h"),
        (WEEK + DAY + HOUR + 60, "1w 1d 1h 1m"),
        # Negative = over-logged remaining: magnitude must survive (was floored to
        # "0m", which the UI rendered as a nonsense "0m over").
        (-(2 * HOUR + 45 * 60), "-2h 45m"),
        (-DAY, "-1d"),
    ],
)
def test_format_duration(seconds, text):
    assert format_duration(seconds) == text


def test_parse_format_round_trip():
    for seconds in (60, 1800, 3600, DAY, WEEK, WEEK + 2 * HOUR + 30 * 60):
        assert parse_duration(format_duration(seconds)) == seconds


def test_configurable_working_day():
    # A 7.5h day (450m) changes what "1d" means.
    assert parse_duration("1d", hours_per_day=8) == 8 * HOUR
    assert format_duration(6 * HOUR, hours_per_day=6) == "1d"
