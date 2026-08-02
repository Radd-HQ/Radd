"""Cycle-management core (Jira-style close + recurring series).

Pure tests: the status derivation the whole UI keys off (completed_at-aware),
series membership by name, and draft-name generation with collision skipping.
The close flow itself runs through the items/cycles services end-to-end."""

from datetime import date, datetime

from radd.modules.cycles.types import (
    CycleStatus,
    cycle_label,
    cycle_status,
    next_weekday_on_or_after,
    parse_cycle_name,
    same_label,
    series_draft_names,
    series_windows,
)

TODAY = date(2026, 7, 21)


def test_status_completed_at_wins_over_dates():
    # explicitly closed mid-window → completed even though today is inside the range
    stamp = datetime(2026, 7, 21, 12, 0)
    assert cycle_status(date(2026, 7, 14), date(2026, 7, 28), TODAY, stamp) is CycleStatus.COMPLETED
    # and a closed draft (no dates) is completed, not draft
    assert cycle_status(None, None, TODAY, stamp) is CycleStatus.COMPLETED


def test_status_without_close_marker_is_date_derived():
    assert cycle_status(date(2026, 7, 14), date(2026, 7, 28), TODAY, None) is CycleStatus.ACTIVE
    assert cycle_status(date(2026, 8, 1), date(2026, 8, 14), TODAY, None) is CycleStatus.UPCOMING
    assert cycle_status(date(2026, 6, 1), date(2026, 6, 14), TODAY, None) is CycleStatus.COMPLETED
    assert cycle_status(None, None, TODAY, None) is CycleStatus.DRAFT


def test_parse_cycle_name_and_label():
    assert parse_cycle_name("PIPE - 115") == ("PIPE", 115)
    assert parse_cycle_name("PIPE-114") == ("PIPE", 114)  # separators are cosmetic
    assert parse_cycle_name("Sprint 007") == ("Sprint", 7)
    assert parse_cycle_name("Kickoff") is None
    assert parse_cycle_name("2024") is None  # a bare number has no label
    assert cycle_label("PIPE - 115") == "PIPE"


def test_same_label_is_case_insensitive_and_none_safe():
    assert same_label("PIPE", "pipe") is True
    assert same_label("PIPE", "DEV") is False
    assert same_label(None, "PIPE") is False
    assert same_label(None, None) is False


def test_series_draft_names_counts_from_next_number():
    names, next_number = series_draft_names([], "PIPE", 119, 2)
    assert names == ["PIPE - 119", "PIPE - 120"]
    assert next_number == 121


def test_series_draft_names_skips_taken_numbers():
    # a Jira import already holds 120 — provisioning must jump over it
    names, next_number = series_draft_names(["PIPE - 120"], "PIPE", 119, 2)
    assert names == ["PIPE - 119", "PIPE - 121"]
    assert next_number == 122


MONDAY = 0


def test_next_weekday_snaps_forward_only():
    assert next_weekday_on_or_after(date(2026, 7, 21), MONDAY) == date(2026, 7, 27)  # Tue → next Mon
    assert next_weekday_on_or_after(date(2026, 7, 27), MONDAY) == date(2026, 7, 27)  # Mon stays


def test_series_windows_chain_back_to_back():
    # 2-week Monday cadence after a cycle ending Sun Aug 2 → Aug 3–16, Aug 17–30
    windows = series_windows(date(2026, 8, 2), TODAY, MONDAY, 14, 2)
    assert windows == [
        (date(2026, 8, 3), date(2026, 8, 16)),
        (date(2026, 8, 17), date(2026, 8, 30)),
    ]


def test_series_windows_unaligned_duration_gaps_to_weekday():
    # 10-day Monday cycles: each ends Wednesday, the next snaps to the following Monday
    windows = series_windows(None, date(2026, 7, 27), MONDAY, 10, 2)
    assert windows == [
        (date(2026, 7, 27), date(2026, 8, 5)),
        (date(2026, 8, 10), date(2026, 8, 19)),
    ]


def test_series_windows_stale_chain_restarts_from_today():
    # the label's last scheduled cycle ended long ago — plan from today, not history
    windows = series_windows(date(2026, 1, 4), TODAY, MONDAY, 14, 1)
    assert windows == [(date(2026, 7, 27), date(2026, 8, 9))]
