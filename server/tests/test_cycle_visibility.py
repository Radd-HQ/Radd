"""Team-restricted cycle visibility (spec 60) — the invariant the sidebar,
pickers, and cycle page all lean on: no teams = public; teams = members only;
cycle managers always see everything."""

import uuid
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.cycles import service as cycles
from radd.modules.cycles.schemas import CycleCreate, CycleUpdate
from radd.modules.teams import service as teams
from radd.modules.teams.schemas import TeamCreate

TODAY = date(2026, 7, 22)


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _user(db, *, admin=False) -> User:
    user = User(
        email=f"cv-{uuid.uuid4().hex[:8]}@example.com",
        name="Cycle Viz",
        instance_role=(InstanceRole.ADMIN if admin else InstanceRole.MEMBER).value,
    )
    db.add(user)
    await db.flush()
    return user


async def test_team_restricted_cycles_hide_from_non_members(db):
    run = uuid.uuid4().hex[:6]
    member = await _user(db)
    manager = await _user(db, admin=True)
    team_a = await teams.create_team(db, TeamCreate(name=f"A{run}"))
    team_b = await teams.create_team(db, TeamCreate(name=f"B{run}"))
    await teams.add_team_member(db, team_a.id, member.id)

    # Distinct names so the assertions survive the shared DB's other global cycles.
    public = await cycles.create_cycle(
        db, CycleCreate(name=f"Public {run}"), TODAY
    )
    mine = await cycles.create_cycle(
        db,
        CycleCreate(name=f"Mine {run}", team_ids=[team_a.id]),
        TODAY,
    )
    theirs = await cycles.create_cycle(
        db,
        CycleCreate(name=f"Theirs {run}", team_ids=[team_b.id]),
        TODAY,
    )
    assert mine.team_ids == [team_a.id]

    # Cycles are global now, so assert on THIS test's cycles as a subset.
    visible, _ = await cycles.visible_cycles(db, member, today=TODAY)
    names = {c.name for c in visible}
    assert f"Public {run}" in names and f"Mine {run}" in names
    assert f"Theirs {run}" not in names  # restricted to team_b, member isn't in it
    # cycle managers (instance admin here) see everything
    visible, _ = await cycles.visible_cycles(db, manager, today=TODAY)
    names = {c.name for c in visible}
    assert {f"Public {run}", f"Mine {run}", f"Theirs {run}"} <= names

    # single-cycle guard mirrors the list
    theirs_row = await cycles.get_cycle(db, theirs.id)
    assert await cycles.cycle_visible_to(db, theirs_row, member) is False
    assert await cycles.cycle_visible_to(db, theirs_row, manager) is True
    public_row = await cycles.get_cycle(db, public.id)
    assert await cycles.cycle_visible_to(db, public_row, member) is True

    # [] on update makes it public again; omitted leaves it restricted
    updated = await cycles.update_cycle(db, theirs.id, CycleUpdate(goal="g"), TODAY)
    assert updated.team_ids == [team_b.id]
    updated = await cycles.update_cycle(db, theirs.id, CycleUpdate(team_ids=[]), TODAY)
    assert updated.team_ids == []
    theirs_row = await cycles.get_cycle(db, theirs.id)
    assert await cycles.cycle_visible_to(db, theirs_row, member) is True


async def test_unknown_team_rejected(db):
    # Teams are global now (no cross-workspace concept) — the remaining guard is
    # that an UNKNOWN team id can't be attached to a cycle.
    run = uuid.uuid4().hex[:6]
    from radd.exceptions import ConflictError

    with pytest.raises(ConflictError):
        await cycles.create_cycle(
            db,
            CycleCreate(name=f"X {run}", team_ids=[uuid.uuid4()]),
            TODAY,
        )
