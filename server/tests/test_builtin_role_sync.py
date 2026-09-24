"""RADD-1305 — built-in roles cannot drift, Staff is gone, umbrellas imply
what they administer.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.auth import roles
from radd.modules.auth.models import Role
from radd.modules.auth.types import BUILTIN_ROLES, BuiltinRoleKey, expand_permissions
from radd.modules.events.models import Event


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
        await session.rollback()
    await engine.dispose()


def _spec(key: BuiltinRoleKey):
    return next(spec for spec in BUILTIN_ROLES if spec.key == key)


async def test_a_drifted_builtin_converges_on_the_code_and_says_so(db):
    await roles.ensure_builtin_roles(db)
    member = await db.scalar(select(Role).where(Role.key == BuiltinRoleKey.MEMBER.value))
    member.permissions = ["item.read"]  # drift: the row lost atoms
    member.name = "Renamed by hand"
    await db.flush()

    await roles.ensure_builtin_roles(db)
    assert sorted(member.permissions) == sorted(str(p) for p in _spec(BuiltinRoleKey.MEMBER).permissions)
    assert member.name == _spec(BuiltinRoleKey.MEMBER).name
    audited = await db.scalar(
        select(Event).where(Event.entity_id == str(member.id), Event.event_type == "role.updated")
        .order_by(Event.id.desc())
    )
    assert audited is not None and audited.payload.get("changes")  # the correction is in the ledger


async def test_an_in_sync_builtin_is_left_alone(db):
    await roles.ensure_builtin_roles(db)
    viewer = await db.scalar(select(Role).where(Role.key == BuiltinRoleKey.VIEWER.value))
    before = await db.scalar(
        select(Event.id).where(Event.entity_id == str(viewer.id)).order_by(Event.id.desc())
    )
    await roles.ensure_builtin_roles(db)
    after = await db.scalar(
        select(Event.id).where(Event.entity_id == str(viewer.id)).order_by(Event.id.desc())
    )
    assert before == after  # no event when nothing changed


async def test_baseline_edits_survive_startup(db):
    await roles.ensure_builtin_roles(db)
    baseline = await db.scalar(select(Role).where(Role.key == BuiltinRoleKey.BASELINE.value))
    edited = [*baseline.permissions, f"x-{uuid.uuid4().hex[:4]}"]
    baseline.permissions = edited
    await db.flush()
    await roles.ensure_builtin_roles(db)
    assert baseline.permissions == edited


async def test_staff_is_gone(db):
    assert await db.scalar(select(Role.id).where(Role.key == "staff")) is None


def test_umbrellas_imply_what_they_administer():
    assert {"page.delete", "page.write", "page.read"} <= expand_permissions({"page.manage"})
    assert "page.read" in expand_permissions({"page.write"})
    assert "item.read" in expand_permissions({"project.manage"})
    assert {"project.create", "project.delete"} <= expand_permissions({"global.manage"})


def _effective(key: BuiltinRoleKey) -> frozenset[str]:
    return expand_permissions({str(p) for p in _spec(key).permissions})


def _scope(atoms: frozenset[str], prefix: str) -> frozenset[str]:
    return frozenset(a for a in atoms if a.startswith(prefix))


def test_the_ladder_is_a_superset_chain_at_both_scopes():
    """RADD-1302: Viewer ⊂ Member ⊂ Manager — as a whole, AND separately for
    the atoms a project grant applies (item/...) and a space grant applies
    (page.*). Before, Member lacked Viewer's page.read and Admin lacked
    Member's page.write."""
    viewer, member, manager = (_effective(k) for k in (
        BuiltinRoleKey.VIEWER, BuiltinRoleKey.MEMBER, BuiltinRoleKey.MANAGER))
    assert viewer < member < manager
    pages = [_scope(r, "page.") for r in (viewer, member, manager)]
    assert pages[0] < pages[1] < pages[2]  # read ⊂ write ⊂ manage on a space
    assert "form.manage" not in member and "form.manage" in manager
    assert {"sla.update", "participant.manage", "page.manage"} <= manager


def test_the_manager_is_not_called_admin():
    assert _spec(BuiltinRoleKey.MANAGER).name == "Manager"
    assert all(spec.key.value != "admin" for spec in BUILTIN_ROLES)
