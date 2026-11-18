"""RADD-1576: whose time a person may see on the timesheet.

The rule every timesheet surface leans on: `timesheet.view` (global) sees
whoever is asked for; a team's owner or manager sees that team's members when
they ask for them; everyone else sees themselves. A sheet nobody narrowed is
never widened by stewardship.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.modules.auth import authz, principals, roles, service as auth
from radd.modules.auth.schemas import UserCreate
from radd.modules.auth.types import InstanceRole
from radd.modules.teams import service as teams
from radd.modules.teams.models import Team, TeamManager
from radd.modules.timelogging import timesheet


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        await roles.ensure_builtin_roles(session)
        await principals.ensure_builtin_accounts(session)
        yield session
        await session.rollback()
    await engine.dispose()


async def _person(db, name, role=InstanceRole.MEMBER):
    return await auth.create_user(
        db,
        UserCreate(
            email=f"{name}-{uuid.uuid4().hex[:8]}@people.example.com",
            name=name,
            password=f"pw-{uuid.uuid4().hex}",
            instance_role=role,
        ),
    )


async def test_a_team_steward_sees_their_team_when_asked_and_nobody_else(db):
    lead, owner = await _person(db, "lead"), await _person(db, "owner")
    member, outsider = await _person(db, "member"), await _person(db, "outsider")
    admin = await _person(db, "admin", InstanceRole.ADMIN)
    led = Team(name=f"led-{uuid.uuid4().hex[:8]}", owner_id=owner.id)
    other = Team(name=f"other-{uuid.uuid4().hex[:8]}")
    db.add_all([led, other])
    await db.flush()
    db.add(TeamManager(team_id=led.id, user_id=lead.id))
    await teams.add_team_member(db, led.id, member.id)
    await teams.add_team_member(db, other.id, outsider.id)
    await db.flush()

    # The premise: none of the three holds the global permission.
    for person in (lead, owner, member):
        held = await authz.effective_permissions(db, person)
        assert authz.Permission.TIMESHEET_VIEW not in held

    everyone = {lead.id, owner.id, member.id, outsider.id}
    for steward in (lead, owner):
        assert await timesheet.visible_user_ids(db, steward, set(everyone)) == {steward.id, member.id}
        assert await timesheet.visible_user_ids(db, steward, {outsider.id}) == set()
        # Nobody asked for anyone: their own time, not the team's.
        assert await timesheet.visible_user_ids(db, steward, None) == {steward.id}
        assert [team.id for team in await timesheet.reviewable_teams(db, steward)] == [led.id]

    assert await timesheet.visible_user_ids(db, member, set(everyone)) == {member.id}
    assert await timesheet.reviewable_teams(db, member) == []

    assert await timesheet.visible_user_ids(db, admin, set(everyone)) == everyone
    assert await timesheet.visible_user_ids(db, admin, None) is None
    assert {led.id, other.id} <= {team.id for team in await timesheet.reviewable_teams(db, admin)}
