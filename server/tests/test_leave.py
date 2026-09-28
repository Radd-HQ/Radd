"""Leave + team holidays (timesheet wave; hours in RADD-1481) — the core
invariants: authz (self / steward / admin), holiday expansion to members, the
now-view the app-wide indicator renders from, and the zone a timed row is read
in. DB-backed, rolled back."""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from radd.exceptions import ConflictError, ForbiddenError
from radd.modules.auth.types import InstanceRole
from radd.modules.leave import service as leave
from radd.modules.leave.schemas import LeaveCreate
from radd.modules.leave.types import LeaveKind
from radd.modules.teams import service as teams_service
from radd.modules.teams.schemas import TeamCreate

from _factories import make_user

TODAY = date(2026, 7, 30)
NOON = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)
LONDON = ZoneInfo("Europe/London")


def _span(days: int = 2) -> dict:
    return {"start_date": TODAY, "end_date": TODAY + timedelta(days=days)}


async def _team(db, owner, *members):
    team = await teams_service.create_team(
        db, TeamCreate(name=f"T-{uuid.uuid4().hex[:6]}", owner_id=owner.id), actor_id=owner.id
    )
    for member in members:
        await teams_service.add_team_member(db, team.id, member.id)
    return team


async def _away(db, at: datetime) -> set[uuid.UUID]:
    return {row.user_id for row in await leave.current(db, at)}


async def test_own_leave_defaults_to_actor(db):
    actor = await make_user(db)
    period = await leave.create(db, actor, LeaveCreate(label="PTO", **_span()))
    assert period.user_id == actor.id
    assert period.kind == LeaveKind.LEAVE.value
    assert period.timezone == "UTC"  # nothing on the profile, nothing in the request
    assert [p.id for p in await leave.list_for_user(db, actor.id)] == [period.id]


async def test_stranger_cannot_record_others_leave(db):
    actor, other = await make_user(db), await make_user(db)
    with pytest.raises(ForbiddenError):
        await leave.create(db, actor, LeaveCreate(user_id=other.id, **_span()))


async def test_steward_covers_for_member(db):
    steward, member = await make_user(db), await make_user(db)
    await _team(db, steward, member)
    period = await leave.create(db, steward, LeaveCreate(user_id=member.id, **_span()))
    assert period.user_id == member.id


async def test_holiday_is_admin_only_and_expands_to_members(db):
    admin = await make_user(db, role=InstanceRole.ADMIN)
    member, outsider = await make_user(db), await make_user(db)
    team = await teams_service.create_team(
        db, TeamCreate(name=f"H-{uuid.uuid4().hex[:6]}"), actor_id=admin.id
    )
    await teams_service.add_team_member(db, team.id, member.id)

    with pytest.raises(ForbiddenError):
        await leave.create(db, member, LeaveCreate(team_id=team.id, label="Eid", **_span()))

    period = await leave.create(db, admin, LeaveCreate(team_id=team.id, label="Eid", **_span()))
    assert period.kind == LeaveKind.HOLIDAY.value

    entries = await leave.calendar(db, TODAY, TODAY)
    users_on_leave = {entry.user_id for entry in entries}
    assert member.id in users_on_leave
    assert outsider.id not in users_on_leave
    assert member.id in await _away(db, NOON)


async def test_current_reports_longest_absence_per_user(db):
    actor = await make_user(db)
    await leave.create(db, actor, LeaveCreate(label="short", start_date=TODAY, end_date=TODAY))
    await leave.create(
        db, actor, LeaveCreate(label="long", start_date=TODAY, end_date=TODAY + timedelta(days=9))
    )
    rows = [row for row in await leave.current(db, NOON) if row.user_id == actor.id]
    assert len(rows) == 1
    assert rows[0].until == TODAY + timedelta(days=9)
    assert rows[0].until_time is None
    # Not away next month.
    later = await leave.calendar(db, TODAY + timedelta(days=30), TODAY + timedelta(days=30))
    assert actor.id not in {entry.user_id for entry in later}


async def test_subject_validation(db):
    actor = await make_user(db, role=InstanceRole.ADMIN)
    team = await teams_service.create_team(
        db, TeamCreate(name=f"V-{uuid.uuid4().hex[:6]}"), actor_id=actor.id
    )
    with pytest.raises(ConflictError):
        await leave.create(db, actor, LeaveCreate(user_id=actor.id, team_id=team.id, **_span()))
    with pytest.raises(ConflictError):
        await leave.create(
            db, actor, LeaveCreate(start_date=TODAY, end_date=TODAY - timedelta(days=1))
        )


# --- hours (RADD-1481) --------------------------------------------------------


async def test_a_timed_start_is_away_from_that_hour_in_its_own_zone(db):
    """Monday 16:00 → Tuesday (whole day), read in the subject's profile zone:
    the person is here at 14:00 London, away at 16:30, and back on Wednesday."""
    actor = await make_user(db, timezone="Europe/London")
    period = await leave.create(
        db,
        actor,
        LeaveCreate(start_date=TODAY, end_date=TODAY + timedelta(days=1), start_time=time(16, 0)),
    )
    assert period.timezone == "Europe/London"
    assert actor.id not in await _away(db, datetime(2026, 7, 30, 14, 0, tzinfo=LONDON))
    assert actor.id in await _away(db, datetime(2026, 7, 30, 16, 30, tzinfo=LONDON))
    assert actor.id in await _away(db, datetime(2026, 7, 31, 23, 30, tzinfo=LONDON))
    assert actor.id not in await _away(db, datetime(2026, 8, 1, 0, 30, tzinfo=LONDON))
    # The same instants expressed in UTC give the same answer: the row's zone decides.
    assert actor.id in await _away(db, datetime(2026, 7, 30, 15, 30, tzinfo=UTC))  # 16:30 BST
    assert actor.id not in await _away(db, datetime(2026, 7, 30, 14, 30, tzinfo=UTC))  # 15:30 BST


async def test_a_timed_end_stops_at_that_hour(db):
    """12:00 on the 30th until 16:00 on the 3rd: away at 15:59 on the 3rd, not at 16:00."""
    actor = await make_user(db)
    zone = ZoneInfo("America/New_York")
    period = await leave.create(
        db,
        actor,
        LeaveCreate(
            start_date=TODAY,
            end_date=date(2026, 8, 3),
            start_time=time(12, 0),
            end_time=time(16, 0),
            timezone="America/New_York",
        ),
    )
    assert period.timezone == "America/New_York"  # the request wins over the profile
    assert actor.id not in await _away(db, datetime(2026, 7, 30, 11, 59, tzinfo=zone))
    assert actor.id in await _away(db, datetime(2026, 7, 30, 12, 0, tzinfo=zone))
    row = next(r for r in await leave.current(db, datetime(2026, 8, 3, 15, 59, tzinfo=zone)) if r.user_id == actor.id)
    assert (row.until, row.until_time, row.timezone) == (date(2026, 8, 3), time(16, 0), "America/New_York")
    assert actor.id not in await _away(db, datetime(2026, 8, 3, 16, 0, tzinfo=zone))
    # The calendar carries the times for the timesheet's boundary cells.
    entry = next(e for e in await leave.calendar(db, TODAY, TODAY) if e.user_id == actor.id)
    assert (entry.start_time, entry.end_time) == (time(12, 0), time(16, 0))


async def test_same_day_times_must_be_ordered_and_a_blank_end_is_the_whole_day(db):
    actor = await make_user(db)
    with pytest.raises(ConflictError):
        await leave.create(
            db,
            actor,
            LeaveCreate(start_date=TODAY, end_date=TODAY, start_time=time(16, 0), end_time=time(12, 0)),
        )
    period = await leave.create(
        db, actor, LeaveCreate(start_date=TODAY, end_date=TODAY, start_time=time(12, 0))
    )
    start, end = leave.span(period)
    assert (start.hour, end.date()) == (12, TODAY + timedelta(days=1))


async def test_a_holiday_is_a_whole_day(db):
    admin = await make_user(db, role=InstanceRole.ADMIN)
    team = await teams_service.create_team(
        db, TeamCreate(name=f"W-{uuid.uuid4().hex[:6]}"), actor_id=admin.id
    )
    with pytest.raises(ConflictError):
        await leave.create(
            db, admin, LeaveCreate(team_id=team.id, label="Eve", start_time=time(13, 0), **_span())
        )


async def test_zone_resolves_request_then_subject_then_actor(db):
    steward = await make_user(db, timezone="Asia/Tokyo")
    paris, blank = await make_user(db, timezone="Europe/Paris"), await make_user(db)
    await _team(db, steward, paris, blank)
    assert (await leave.create(db, steward, LeaveCreate(user_id=paris.id, **_span()))).timezone == "Europe/Paris"
    assert (await leave.create(db, steward, LeaveCreate(user_id=blank.id, **_span()))).timezone == "Asia/Tokyo"
    assert (await leave.create(db, steward, LeaveCreate(**_span()))).timezone == "Asia/Tokyo"
    with pytest.raises(ConflictError):
        await leave.create(db, steward, LeaveCreate(timezone="Mars/Olympus", **_span()))


async def test_stewards_see_their_teams_leave_and_nobody_else_does(db):
    steward, member, stranger = await make_user(db), await make_user(db), await make_user(db)
    admin = await make_user(db, role=InstanceRole.ADMIN)
    team = await _team(db, steward, member)
    period = await leave.create(db, steward, LeaveCreate(user_id=member.id, label="ooo", **_span()))

    assert [t.id for t in await leave.stewarded_teams(db, steward)] == [team.id]
    assert await leave.stewarded_teams(db, member) == []
    assert team.id in {t.id for t in await leave.stewarded_teams(db, admin)}

    assert await leave.may_manage_team(db, steward, team)
    assert await leave.may_manage_team(db, admin, team)
    assert not await leave.may_manage_team(db, stranger, team)
    assert not await leave.may_manage_team(db, member, team)

    assert [p.id for p in await leave.list_for_team(db, team.id)] == [period.id]
    assert await leave.list_for_team(db, team.id, since=TODAY + timedelta(days=30)) == []
