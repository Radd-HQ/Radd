"""Monthly and cron schedules (RADD-909/910).

Pure — `radd/schedule.py` takes no session. The interesting cases are the ones a
schedule gets wrong quietly: a month that has no 31st, a DST boundary, and a cron
expression that would fire every minute.

Shape validation lives here too because it moved into the shared util: automations
and backups each had their own copy, already subtly different, and two more kinds
in two places is how that becomes three differences.
"""

import uuid
from datetime import datetime, timedelta

import pytest

from radd.schedule import (
    MIN_INTERVAL_MINUTES,
    ScheduleKind,
    cron_shortest_gap,
    next_run,
    validate_config,
)


# --- monthly ------------------------------------------------------------------


def test_monthly_fires_on_the_named_day():
    cfg = {"kind": "monthly", "time": "09:00", "day": 15}
    assert next_run(cfg, datetime(2026, 7, 1, 10, 0), "UTC") == datetime(2026, 7, 15, 9, 0)


def test_monthly_rolls_into_the_next_month_once_the_day_has_passed():
    cfg = {"kind": "monthly", "time": "09:00", "day": 15}
    assert next_run(cfg, datetime(2026, 7, 15, 9, 0), "UTC") == datetime(2026, 8, 15, 9, 0)


def test_the_31st_clamps_to_the_end_of_a_short_month():
    """The whole reason this is not a `while` over calendar days. Skipping is the
    other reading of "monthly on the 31st" and it is the wrong one: a maintenance
    ticket that silently misses four months a year is worse than one that arrives
    three days early."""
    cfg = {"kind": "monthly", "time": "09:00", "day": 31}
    assert next_run(cfg, datetime(2026, 2, 1, 0, 0), "UTC") == datetime(2026, 2, 28, 9, 0)
    # A leap February takes the 29th.
    assert next_run(cfg, datetime(2028, 2, 1, 0, 0), "UTC") == datetime(2028, 2, 29, 9, 0)
    # And April, which has 30.
    assert next_run(cfg, datetime(2026, 4, 1, 0, 0), "UTC") == datetime(2026, 4, 30, 9, 0)


def test_monthly_keeps_local_time_across_a_dst_change():
    """09:00 in New York is 13:00 UTC in summer and 14:00 in winter. The LOCAL
    time is what someone wrote down, so that is what stays put."""
    cfg = {"kind": "monthly", "time": "09:00", "day": 5}
    assert next_run(cfg, datetime(2026, 10, 6, 0, 0), "America/New_York") == datetime(
        2026, 11, 5, 14, 0
    )
    assert next_run(cfg, datetime(2026, 9, 6, 0, 0), "America/New_York") == datetime(
        2026, 10, 5, 13, 0
    )


def test_monthly_crosses_a_year_boundary():
    cfg = {"kind": "monthly", "time": "09:00", "day": 3}
    assert next_run(cfg, datetime(2026, 12, 4, 0, 0), "UTC") == datetime(2027, 1, 3, 9, 0)


# --- cron ---------------------------------------------------------------------


def test_cron_resolves_the_next_matching_moment():
    cfg = {"kind": "cron", "expression": "0 9 * * 1"}  # 09:00 every Monday
    # 2026-07-23 is a Thursday.
    assert next_run(cfg, datetime(2026, 7, 23, 10, 0), "UTC") == datetime(2026, 7, 27, 9, 0)


def test_cron_is_interpreted_in_the_scheduler_timezone():
    """Not UTC. "0 9 * * *" means nine in the morning where the instance thinks
    it lives, exactly as the other kinds do."""
    cfg = {"kind": "cron", "expression": "0 9 * * *"}
    assert next_run(cfg, datetime(2026, 7, 23, 0, 0), "Europe/Berlin") == datetime(
        2026, 7, 23, 7, 0
    )


def test_cron_handles_step_and_range_syntax():
    cfg = {"kind": "cron", "expression": "0 */6 * * *"}
    assert next_run(cfg, datetime(2026, 7, 23, 7, 0), "UTC") == datetime(2026, 7, 23, 12, 0)


def test_the_shortest_gap_is_measured_not_declared():
    """A cron config names no interval, so the floor cannot be read off a field —
    it is measured from consecutive occurrences."""
    assert cron_shortest_gap("* * * * *", "UTC") == timedelta(minutes=1)
    assert cron_shortest_gap("*/15 * * * *", "UTC") == timedelta(minutes=15)


# --- shape validation ---------------------------------------------------------


def test_a_cron_that_fires_every_minute_is_refused():
    with pytest.raises(ValueError, match="more often"):
        validate_config({"kind": "cron", "expression": "* * * * *"})


def test_a_cron_at_the_floor_is_allowed():
    validate_config({"kind": "cron", "expression": f"*/{MIN_INTERVAL_MINUTES} * * * *"})


def test_nonsense_cron_is_refused_with_the_expression_named():
    with pytest.raises(ValueError, match="not a valid cron"):
        validate_config({"kind": "cron", "expression": "every tuesday please"})


def test_each_kind_refuses_the_other_kinds_fields():
    """The check that had drifted between the two copies. A stray field is a
    half-edited form, and accepting it stores a schedule that does not mean what
    the person who saved it thinks."""
    with pytest.raises(ValueError, match="does not take"):
        validate_config({"kind": "daily", "time": "09:00", "weekdays": [1]})
    with pytest.raises(ValueError, match="does not take"):
        validate_config({"kind": "monthly", "time": "09:00", "day": 5, "minutes": 30})
    with pytest.raises(ValueError, match="does not take"):
        validate_config({"kind": "cron", "expression": "0 9 * * 1", "time": "09:00"})


def test_an_empty_weekday_list_reads_as_absent():
    """Stored configs carry `weekdays: []` on daily schedules — the backup form
    has always written it that way — so treating an empty list as "supplied"
    would reject every schedule already in the database."""
    validate_config({"kind": "daily", "time": "09:00", "weekdays": []})


def test_missing_fields_name_what_is_missing():
    with pytest.raises(ValueError, match="needs `day`"):
        validate_config({"kind": "monthly", "time": "09:00"})
    with pytest.raises(ValueError, match="needs `expression`"):
        validate_config({"kind": "cron"})


def test_the_day_of_the_month_is_bounded():
    with pytest.raises(ValueError, match="1 to 31"):
        validate_config({"kind": "monthly", "time": "09:00", "day": 32})


def test_the_interval_floor_still_holds():
    with pytest.raises(ValueError, match="at most every"):
        validate_config({"kind": "interval", "minutes": 1})


def test_every_kind_the_builder_offers_can_be_validated():
    """The catalog and the validator must agree on the vocabulary — a kind
    offered in the dropdown that the server rejects is a dead option."""
    from radd.modules.automations import catalog

    offered = {kind for kind, _label in catalog.SCHEDULE_KINDS}
    assert offered == set(ScheduleKind), "the builder offers a different set of kinds"


# --- the shape reaches the API ------------------------------------------------


async def test_a_schedule_trigger_is_validated_when_the_automation_is_saved(db, admin):
    """When triggers moved into node params, `params` became an untyped envelope
    and the schedule model stopped being applied to them — so a bad schedule was
    stored happily and became a 500 in the scheduler. It is a 409 on the form."""
    from radd.exceptions import ConflictError
    from radd.modules.automations import service as automations
    from radd.modules.automations.schemas import RuleCreate

    def rule(schedule):
        return RuleCreate(
            name=f"sched-{uuid.uuid4().hex[:6]}",
            nodes=[
                {
                    "id": "t",
                    "kind": "trigger",
                    "type": "trigger.event",
                    "params": {"event": "schedule", "schedule": schedule, "query": ""},
                }
            ],
            edges=[],
        )

    for bad in (
        {"kind": "cron", "expression": "* * * * *"},   # under the floor
        {"kind": "cron", "expression": "not a cron"},  # unparseable
        {"kind": "monthly", "time": "09:00", "day": 40},
        {"kind": "monthly", "time": "09:00"},          # no day
        {"kind": "daily"},                             # no time
    ):
        with pytest.raises(ConflictError):
            await automations.create_rule(db, rule(bad), actor_id=admin.id)

    good = await automations.create_rule(
        db, rule({"kind": "monthly", "time": "09:00", "day": 31}), actor_id=admin.id
    )
    assert good.id is not None


@pytest.fixture
async def db():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from radd.config import settings

    engine_ = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine_, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine_.dispose()


@pytest.fixture
async def admin(db):
    from radd.modules.auth.models import User
    from radd.modules.auth.types import InstanceRole

    user = User(
        email=f"sched-{uuid.uuid4().hex[:8]}@example.com",
        name="Schedule Tester",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user
