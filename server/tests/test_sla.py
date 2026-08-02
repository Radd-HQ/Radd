"""SLA timer math core (spec 30).

Pure tests of timers.py — deadline computation with pauses, met/late/breach
semantics, and the paused state. The engine's exactly-once breach events are
exercised live (isolated DB).
"""

from datetime import datetime, timedelta

from radd.modules.slas.timers import deadline, evaluate, in_pause, merge_intervals

T0 = datetime(2026, 7, 1, 10, 0, 0)


def _m(minutes: float) -> timedelta:
    return timedelta(minutes=minutes)


# --- deadline ---


def test_deadline_without_pauses():
    assert deadline(T0, 60 * 60, [], T0) == T0 + _m(60)


def test_pause_before_deadline_pushes_it_out():
    # 20 minutes paused inside the first hour → deadline slides 20 minutes.
    pauses = [(T0 + _m(10), T0 + _m(30))]
    assert deadline(T0, 60 * 60, pauses, T0 + _m(90)) == T0 + _m(80)


def test_pause_after_deadline_is_irrelevant():
    pauses = [(T0 + _m(90), T0 + _m(120))]
    assert deadline(T0, 60 * 60, pauses, T0 + _m(150)) == T0 + _m(60)


def test_open_pause_before_target_floats_the_deadline():
    # Paused at +30m with a 60m target and never resumed: no deadline yet.
    assert deadline(T0, 60 * 60, [(T0 + _m(30), None)], T0 + _m(300)) is None


def test_target_reached_before_open_pause_still_has_deadline():
    # 60m target reached at +60m; the pause starts later, deadline stands.
    assert deadline(T0, 60 * 60, [(T0 + _m(90), None)], T0 + _m(300)) == T0 + _m(60)


def test_merge_overlapping_pauses():
    merged = merge_intervals(
        [(T0, T0 + _m(10)), (T0 + _m(5), T0 + _m(20)), (T0 + _m(30), T0 + _m(40))]
    )
    assert merged == [(T0, T0 + _m(20)), (T0 + _m(30), T0 + _m(40))]


# --- evaluate ---


def test_met_in_time():
    status = evaluate(
        started_at=T0, target_seconds=3600, pauses=[], met_at=T0 + _m(45), now=T0 + _m(120)
    )
    assert status.met_at == T0 + _m(45)
    assert status.breached is False
    assert status.remaining_seconds is None


def test_met_late_records_the_miss():
    status = evaluate(
        started_at=T0, target_seconds=3600, pauses=[], met_at=T0 + _m(90), now=T0 + _m(120)
    )
    assert status.breached is True and status.met_at is not None


def test_open_breach_and_remaining():
    breached = evaluate(started_at=T0, target_seconds=3600, pauses=[], met_at=None, now=T0 + _m(61))
    assert breached.breached is True and breached.remaining_seconds is None
    ticking = evaluate(started_at=T0, target_seconds=3600, pauses=[], met_at=None, now=T0 + _m(45))
    assert ticking.breached is False
    assert ticking.remaining_seconds == 15 * 60


def test_parse_work_week():
    from radd.modules.slas.timers import parse_work_week

    assert parse_work_week("mon,tue,wed,thu,fri") == frozenset({0, 1, 2, 3, 4})
    assert parse_work_week("sun, Mon ,THU") == frozenset({6, 0, 3})
    # Garbage/empty falls back to Mon–Fri (a zero-day week would float forever).
    assert parse_work_week("") == frozenset(range(5))
    assert parse_work_week("caturday") == frozenset(range(5))


def test_non_working_pauses_cover_weekends():
    from radd.modules.slas.timers import non_working_pauses

    # is a Wednesday; Sat 4th + Sun 5th are the first weekend.
    pauses = non_working_pauses(T0, T0 + timedelta(days=6), frozenset(range(5)))
    assert pauses == [
        (datetime(2026, 7, 4), datetime(2026, 7, 5)),
        (datetime(2026, 7, 5), datetime(2026, 7, 6)),
    ]


def test_work_week_deadline_skips_the_weekend():
    from radd.modules.slas.timers import non_working_pauses

    # Started Friday 3rd at 10:00 with a 24h working-hours target: Sat+Sun pause,
    # so the deadline lands Monday 6th 10:00 instead of Saturday.
    friday = datetime(2026, 7, 3, 10, 0)
    pauses = non_working_pauses(friday, friday + timedelta(days=10), frozenset(range(5)))
    assert deadline(friday, 24 * 3600, pauses, friday) == datetime(2026, 7, 6, 10, 0)


def test_paused_now_neither_breaches_nor_counts_down():
    pauses = [(T0 + _m(30), None)]
    status = evaluate(
        started_at=T0, target_seconds=3600, pauses=pauses, met_at=None, now=T0 + _m(200)
    )
    assert status.paused is True
    assert status.breached is False
    assert status.due_at is None and status.remaining_seconds is None
    assert in_pause(pauses, T0 + _m(200)) is True


# --- business-hours window (spec 63) ---

NINE = 9 * 60
FIVE_THIRTY = 17 * 60 + 30
EVERY_DAY = frozenset(range(7))
MON_FRI = frozenset(range(5))


def test_business_hours_pauses_clip_each_day():
    from radd.modules.slas.timers import business_hours_pauses

    # One Wednesday: pause [midnight, 09:00) and [17:30, midnight).
    day = datetime(2026, 7, 1)
    pauses = business_hours_pauses(day, day + timedelta(hours=23), NINE, FIVE_THIRTY, EVERY_DAY)
    assert pauses == [
        (day, day + _m(NINE)),
        (day + _m(FIVE_THIRTY), day + timedelta(days=1)),
    ]
    # A midnight-opening window emits no leading pause.
    pauses = business_hours_pauses(day, day + timedelta(hours=23), 0, FIVE_THIRTY, EVERY_DAY)
    assert pauses == [(day + _m(FIVE_THIRTY), day + timedelta(days=1))]


def test_ticket_filed_at_night_starts_burning_at_window_open():
    from radd.modules.slas.timers import business_hours_pauses

    # Filed Wednesday 23:00, 60m target, 9:00–17:30 window: burns from Thursday
    # 9:00, so the deadline is Thursday 10:00.
    filed = datetime(2026, 7, 1, 23, 0)
    pauses = business_hours_pauses(filed, filed + timedelta(days=7), NINE, FIVE_THIRTY, EVERY_DAY)
    assert deadline(filed, 3600, pauses, filed) == datetime(2026, 7, 2, 10, 0)


def test_weekend_and_window_pauses_merge():
    from radd.modules.slas.timers import business_hours_pauses, non_working_pauses

    # Filed Friday 3rd 16:30 with a 2h target: 60m burn to Friday close, the
    # weekend (whole-day pauses) merges with the nightly window pauses, and the
    # remaining 60m burns Monday 9:00–10:00.
    filed = datetime(2026, 7, 3, 16, 30)
    horizon = filed + timedelta(days=10)
    pauses = non_working_pauses(filed, horizon, MON_FRI) + business_hours_pauses(
        filed, horizon, NINE, FIVE_THIRTY, MON_FRI
    )
    assert deadline(filed, 2 * 3600, pauses, filed) == datetime(2026, 7, 6, 10, 0)


def test_target_beyond_a_days_window_rolls_over():
    from radd.modules.slas.timers import business_hours_pauses

    # 16h target inside an 8.5h/day window (every day): filed Wednesday 9:00 —
    # 8.5h Wednesday, 7.5h Thursday → due Thursday 16:30.
    filed = datetime(2026, 7, 1, 9, 0)
    pauses = business_hours_pauses(filed, filed + timedelta(days=7), NINE, FIVE_THIRTY, EVERY_DAY)
    assert deadline(filed, 16 * 3600, pauses, filed) == datetime(2026, 7, 2, 16, 30)


# --- first-match resolution (specs 63/67: policies are project-level) ---


def _policy(name, project_id, *, position=0, enabled=True, priorities=()):
    from radd.modules.slas.models import SlaPolicy

    return SlaPolicy(
        name=name,
        enabled=enabled,
        project_id=project_id,
        position=position,
        priorities=list(priorities),
        response_minutes=60,
    )


def test_first_match_priority_filter_and_position_order():
    import uuid

    from radd.modules.items.models import WorkItem
    from radd.modules.slas.service import first_match, ordered

    project_id = uuid.uuid4()
    blocker = _policy("P1 fast", project_id, position=0, priorities=("blocker",))
    catch_all = _policy("Standard", project_id, position=1)
    disabled = _policy("Off", project_id, position=0, enabled=False, priorities=("blocker",))
    policies = ordered([catch_all, disabled, blocker])

    urgent = WorkItem(project_id=project_id, priority="blocker")
    normal = WorkItem(project_id=project_id, priority="normal")
    # blocker wins the priority policy; normal falls through to the catch-all;
    # the disabled twin (same position) never matches.
    assert first_match(policies, urgent) is blocker
    assert first_match(policies, normal) is catch_all
    # position order beats list order: promote the catch-all above the filter.
    catch_all.position = 0
    blocker.position = 1
    assert first_match(ordered([catch_all, blocker]), urgent) is catch_all


def test_first_match_scope_and_no_match():
    import uuid

    from radd.modules.items.models import WorkItem
    from radd.modules.slas.service import first_match, ordered

    mine = uuid.uuid4()
    other = uuid.uuid4()
    scoped = _policy("Scoped", other, position=0)
    low_only = _policy("Low only", mine, position=1, priorities=("low",))
    policies = ordered([scoped, low_only])
    item = WorkItem(project_id=mine, priority="high")
    # Another project's policy + wrong priority → no policy governs the item.
    assert first_match(policies, item) is None
    assert first_match(ordered([scoped]), WorkItem(project_id=other, priority="high")) is scoped
