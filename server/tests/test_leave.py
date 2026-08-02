"""Leave + team holidays (timesheet wave) — the core invariants:
authz (self / steward / admin), holiday expansion to members, and the
today-view the app-wide indicator renders from. DB-backed, rolled back."""

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.exceptions import ConflictError, ForbiddenError
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.leave import service as leave
from radd.modules.leave.schemas import LeaveCreate
from radd.modules.leave.types import LeaveKind
from radd.modules.teams import service as teams_service
from radd.modules.teams.schemas import TeamCreate

TODAY = date(2026, 7, 30)


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _user(db, *, admin: bool = False) -> User:
    user = User(
        email=f"leave-{uuid.uuid4().hex[:8]}@example.com",
        name="Leave Tester",
        instance_role=(InstanceRole.ADMIN if admin else InstanceRole.MEMBER).value,
    )
    db.add(user)
    await db.flush()
    return user


def _span(days: int = 2) -> dict:
    return {"start_date": TODAY, "end_date": TODAY + timedelta(days=days)}


async def test_own_leave_defaults_to_actor(db):
    actor = await _user(db)
    period = await leave.create(db, actor, LeaveCreate(label="PTO", **_span()))
    assert period.user_id == actor.id
    assert period.kind == LeaveKind.LEAVE.value
    assert [p.id for p in await leave.list_for_user(db, actor.id)] == [period.id]


async def test_stranger_cannot_record_others_leave(db):
    actor, other = await _user(db), await _user(db)
    with pytest.raises(ForbiddenError):
        await leave.create(db, actor, LeaveCreate(user_id=other.id, **_span()))


async def test_steward_covers_for_member(db):
    steward, member = await _user(db), await _user(db)
    team = await teams_service.create_team(
        db, TeamCreate(name=f"T-{uuid.uuid4().hex[:6]}", owner_id=steward.id), actor_id=steward.id
    )
    await teams_service.add_team_member(db, team.id, member.id)
    period = await leave.create(db, steward, LeaveCreate(user_id=member.id, **_span()))
    assert period.user_id == member.id


async def test_holiday_is_admin_only_and_expands_to_members(db):
    admin, member, outsider = await _user(db, admin=True), await _user(db), await _user(db)
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


async def test_current_reports_longest_absence_per_user(db):
    actor = await _user(db)
    await leave.create(db, actor, LeaveCreate(label="short", start_date=TODAY, end_date=TODAY))
    await leave.create(
        db, actor, LeaveCreate(label="long", start_date=TODAY, end_date=TODAY + timedelta(days=9))
    )
    rows = [row for row in await leave.current(db, TODAY) if row.user_id == actor.id]
    assert len(rows) == 1
    assert rows[0].until == TODAY + timedelta(days=9)
    # Not away next month.
    later = await leave.calendar(db, TODAY + timedelta(days=30), TODAY + timedelta(days=30))
    assert actor.id not in {entry.user_id for entry in later}


async def test_subject_validation(db):
    actor = await _user(db, admin=True)
    team = await teams_service.create_team(
        db, TeamCreate(name=f"V-{uuid.uuid4().hex[:6]}"), actor_id=actor.id
    )
    with pytest.raises(ConflictError):
        await leave.create(db, actor, LeaveCreate(user_id=actor.id, team_id=team.id, **_span()))
    with pytest.raises(ConflictError):
        await leave.create(
            db, actor, LeaveCreate(start_date=TODAY, end_date=TODAY - timedelta(days=1))
        )
