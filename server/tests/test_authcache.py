"""Authorization answers are reused across requests only while nothing changed (RADD-1560).

A stale permission is a security bug, so what is asserted here is the cache's
SAFETY, with real transactions: a committed change is seen by the very next
read in another session; a transaction that changed something never files its
uncommitted view; and every table the cached answers come from has its trigger.
"""

import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import delete, select, text

from radd import authcache
from radd.config import settings
from radd.db import SessionLocal
from radd.modules.auth import authz, grants
from radd.modules.auth.models import GlobalRoleGrant, Role, User
from radd.modules.auth.types import BuiltinRoleKey, InstanceRole, Permission
from radd.modules.teams.models import Team, TeamMember

from _factories import make_user


@pytest.fixture
async def person():
    """A committed member with no grants; removed afterwards with what hangs off them."""
    async with SessionLocal() as session:
        user = await make_user(session, role=InstanceRole.MEMBER, name="Cached")
        team = Team(name=f"cache-{uuid.uuid4().hex[:8]}")
        session.add(team)
        await session.commit()
        ids = (user.id, team.id)
    authcache.clear()
    try:
        yield ids
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(Team).where(Team.id == ids[1]))
            await session.execute(delete(User).where(User.id == ids[0]))
            await session.commit()
        authcache.clear()


async def _manager_role_id(session) -> uuid.UUID:
    return await session.scalar(select(Role.id).where(Role.key == BuiltinRoleKey.MANAGER.value))


async def _holds(user_id, permission=Permission.PROJECT_MANAGE) -> bool:
    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        return permission in await authz.effective_permissions(session, user)


async def _statements(user_id) -> int:
    """How many statements one resolution costs, counted on the connection."""
    from sqlalchemy import event

    from radd.db import engine

    seen = []

    def count(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        event.listen(engine.sync_engine, "before_cursor_execute", count)
        try:
            await authz.effective_permissions(session, user)
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", count)
    return len(seen)


def test_every_watched_table_has_its_trigger_in_the_migration():
    (path,) = (Path(__file__).parents[1] / "migrations/versions").glob("d1560authepoch*.py")
    spec = importlib.util.spec_from_file_location("d1560authepoch", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert tuple(migration.WATCHED_TABLES) == authcache.WATCHED_TABLES


async def test_the_triggers_exist_on_the_database(db):
    rows = await db.execute(
        text("SELECT event_object_table FROM information_schema.triggers WHERE trigger_name = 'radd_auth_epoch'")
    )
    assert {row[0] for row in rows} == set(authcache.WATCHED_TABLES)


async def test_a_second_resolution_costs_one_statement(person):
    user_id, _team = person
    first = await _statements(user_id)
    second = await _statements(user_id)
    # The epoch is read; memberships, grants and roles come from memory.
    assert second == 1 and first > second, (first, second)


async def test_a_committed_grant_is_seen_by_the_next_read_and_so_is_its_removal(person):
    user_id, _team = person
    assert not await _holds(user_id)
    assert not await _holds(user_id)  # cached "no"
    async with SessionLocal() as session:
        grant = GlobalRoleGrant(role_id=await _manager_role_id(session), user_id=user_id)
        session.add(grant)
        await session.commit()
        grant_id = grant.id
    assert await _holds(user_id), "a committed grant was not seen: the cache outlived the change"
    assert await _holds(user_id)  # cached "yes"
    async with SessionLocal() as session:
        await session.execute(delete(GlobalRoleGrant).where(GlobalRoleGrant.id == grant_id))
        await session.commit()
    assert not await _holds(user_id), "a revoked grant was still honoured"


async def test_a_grant_through_a_team_follows_the_membership_and_the_teams_deletion(person):
    user_id, team_id = person
    async with SessionLocal() as session:
        session.add(GlobalRoleGrant(role_id=await _manager_role_id(session), team_id=team_id))
        await session.commit()
    assert not await _holds(user_id)
    async with SessionLocal() as session:
        session.add(TeamMember(team_id=team_id, user_id=user_id))
        await session.commit()
    assert await _holds(user_id)
    # Deleting the TEAM removes its members and its grants by cascade: no
    # service code runs, only the database's own triggers.
    async with SessionLocal() as session:
        await session.execute(text("DELETE FROM teams WHERE id = :id"), {"id": team_id})
        await session.commit()
    assert not await _holds(user_id), "a cascade-deleted grant was still honoured"


async def test_a_roles_permissions_changing_is_seen(person):
    user_id, _team = person
    async with SessionLocal() as session:
        role = Role(key=f"cache_{uuid.uuid4().hex[:8]}", name="Cache probe", permissions=["item.read"])
        session.add(role)
        await session.flush()
        session.add(GlobalRoleGrant(role_id=role.id, user_id=user_id))
        await session.commit()
        role_id = role.id
    try:
        assert not await _holds(user_id)
        async with SessionLocal() as session:
            (await session.get(Role, role_id)).permissions = ["item.read", "project.manage"]
            await session.commit()
        assert await _holds(user_id)
    finally:
        async with SessionLocal() as session:
            await session.execute(delete(GlobalRoleGrant).where(GlobalRoleGrant.role_id == role_id))
            await session.execute(delete(Role).where(Role.id == role_id))
            await session.commit()


async def test_an_uncommitted_change_is_read_by_its_own_transaction_and_filed_nowhere(person):
    user_id, _team = person
    assert not await _holds(user_id)
    async with SessionLocal() as session:
        session.add(GlobalRoleGrant(role_id=await _manager_role_id(session), user_id=user_id))
        await session.flush()
        user = await session.get(User, user_id)
        # Its own transaction sees the grant it has not committed…
        assert Permission.PROJECT_MANAGE in await authz.effective_permissions(session, user)
        assert await authcache.current(session) is None
        await session.rollback()
    # …and nobody else ever does: the rolled-back view was not cached.
    assert not await _holds(user_id)


async def test_an_expired_grant_stops_counting_without_any_row_changing(person, monkeypatch):
    from datetime import timedelta

    from radd.clock import utcnow

    user_id, _team = person
    async with SessionLocal() as session:
        session.add(
            GlobalRoleGrant(
                role_id=await _manager_role_id(session), user_id=user_id,
                expires_at=utcnow() + timedelta(hours=1),
            )
        )
        await session.commit()
    assert await _holds(user_id)
    later = utcnow() + timedelta(hours=2)
    monkeypatch.setattr(grants, "utcnow", lambda: later)
    assert not await _holds(user_id), "expiry was cached away"


async def test_turned_off_every_read_asks_the_database(person, monkeypatch):
    user_id, _team = person
    monkeypatch.setattr(settings, "auth_cache", False)
    first = await _statements(user_id)
    assert await _statements(user_id) == first
