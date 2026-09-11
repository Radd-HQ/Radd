"""RADD-814 — scope is a property of the grant: the ladder, the memo, the
declaration.

The containment ladder (global ⊃ {project | space}) was always the resolver's
de-facto behaviour; these pin it as named semantics through the one boolean
seam (`holds`), pin the per-request project-map memo `require_anywhere` now
rides, and pin the `checkable_at` declaration as behaviour-identical
singletons with the `instance` tier retired.

DB-backed; flushed, never committed.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.exceptions import ForbiddenError
from radd.modules.auth import authz, authz_batch, grants as auth_grants, roles as auth_roles
from radd.modules.auth.models import User
from radd.modules.auth.schemas import RoleCreate
from radd.modules.auth.types import (
    Permission,
    PermissionScope,
    checkable_at,
    permission_scope_of,
)
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def member(db) -> User:
    user = User(
        email=f"lad-{uuid.uuid4().hex[:8]}@example.com",
        name="Ladder",
        instance_role="member",
    )
    db.add(user)
    await db.flush()
    await auth_roles.ensure_builtin_roles(db)
    return user


async def _role(db, permissions):
    return await auth_roles.create_role(
        db, RoleCreate(key=f"lad{uuid.uuid4().hex[:6]}", name="L", permissions=permissions)
    )


async def _project(db):
    return await projects_service.create_project(
        db, ProjectCreate(key=f"LD{uuid.uuid4().hex[:4].upper()}", name="P")
    )


# --- the ladder ----------------------------------------------------------------


async def test_global_grant_satisfies_the_project_scope(db, member):
    project = await _project(db)
    role = await _role(db, ["cycle.create"])
    await auth_grants.create_grant(db, role_id=role.id, user_id=member.id)  # instance-wide

    assert await authz.holds(db, member, Permission.CYCLE_CREATE)
    assert await authz.holds(db, member, Permission.CYCLE_CREATE, project=project)
    assert await authz.holds(db, member, Permission.CYCLE_CREATE, any_project=True)


async def test_project_grant_stays_inside_its_project(db, member):
    granted = await _project(db)
    other = await _project(db)
    role = await _role(db, ["item.update"])
    await auth_grants.create_grant(db, role_id=role.id, user_id=member.id, project_id=granted.id)

    assert await authz.holds(db, member, Permission.ITEM_UPDATE, project=granted)
    assert not await authz.holds(db, member, Permission.ITEM_UPDATE, project=other)
    # The cross-project tier is satisfied by ONE project; the global tier is not.
    assert await authz.holds(db, member, Permission.ITEM_UPDATE, any_project=True)
    assert not await authz.holds(db, member, Permission.ITEM_UPDATE)


async def test_require_anywhere_rides_one_memoised_map(db, member):
    project = await _project(db)
    role = await _role(db, ["item.read"])
    await auth_grants.create_grant(db, role_id=role.id, user_id=member.id, project_id=project.id)

    first = await authz.project_permission_map(db, member)
    # Same request, second resolution: the memo answers — identity, not equality.
    assert await authz.project_permission_map(db, member) is first
    held = await authz.require_anywhere(db, member, Permission.ITEM_READ)
    assert project.id in held
    readable = await authz.readable_projects(db, member)
    assert project.id in readable


# --- the declaration -----------------------------------------------------------


def test_checkable_at_is_behaviour_identical_singletons():
    for permission in Permission:
        assert checkable_at(permission) == frozenset({permission_scope_of(permission)})


def test_the_instance_tier_is_retired():
    assert "instance" not in {scope.value for scope in PermissionScope}
    from radd.modules.auth import authz as authz_module

    assert not hasattr(authz_module, "ALL_PERMISSIONS")


# --- the member floor on an EMPTY instance (RADD-1132) -------------------------
#
# `readable_projects` is per-project, so with no projects it is empty for
# everyone. The gate must then fall back to the GLOBAL atom, or a fresh
# install greets its seeded admin with a 403 on every member-floor surface.
# Pinned through both seams rather than by emptying the shared test database:
# what changed is the gate's decision, and that is what is asserted. (The
# Baseline role hands every user item.read@own, which `holds_base` counts as
# the base — so a real user is never on the refusing branch unless an admin
# has emptied the Baseline, which is the case the second assertion models.)


async def test_require_member_on_a_projectless_instance_trusts_the_global_atom(
    db, member, monkeypatch
):
    async def no_projects(session, user):
        return {}

    monkeypatch.setattr(authz_batch, "readable_projects", no_projects)

    async def nothing_globally(session, user):
        return frozenset()

    monkeypatch.setattr(authz_batch, "effective_permissions", nothing_globally)
    with pytest.raises(ForbiddenError):
        await authz_batch.require_member(db, member)

    async def item_read_globally(session, user):
        return frozenset({Permission.ITEM_READ})

    monkeypatch.setattr(authz_batch, "effective_permissions", item_read_globally)
    assert await authz_batch.require_member(db, member) == {}
