"""Deleting a user transfers CONTENT, never access (RADD-784): memberships, grants,
delegation and shares are destroyed, so the delete refuses a successor holding
LESS than the leaver and names the missing atoms per scope. The comparison is
lattice-aware (`item.read` covers `item.read@own`); an admin leaver needs an
admin successor.
"""

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import ConflictError
from radd.modules import workflow  # noqa: F401 — registers the default-state hook
from radd.modules.auth import roles as auth_roles, service as auth_service
from radd.modules.auth.models import GlobalRoleGrant, Role, User
from radd.modules.auth.service import _permission_gaps, successor_viability
from radd.modules.auth.types import BuiltinRoleKey, InstanceRole
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate

from _factories import make_project


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        await auth_roles.ensure_builtin_roles(session)
        yield session
        await session.rollback()
    await engine.dispose()


async def _user(db, label, *, role=InstanceRole.MEMBER) -> User:
    user = User(
        email=f"sv-{label}-{uuid.uuid4().hex[:6]}@example.com",
        name=f"{label.title()} Person",
        instance_role=role.value,
        active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _member_role_id(db) -> uuid.UUID:
    return (
        await db.execute(select(Role.id).where(Role.key == BuiltinRoleKey.MEMBER.value))
    ).scalar_one()


async def _join(db, project, user) -> None:
    db.add(
        GlobalRoleGrant(
            project_id=project.id, user_id=user.id, role_id=await _member_role_id(db)
        )
    )
    await db.flush()


def test_gaps_are_lattice_aware():
    theirs = frozenset({"item.read@own", "item.update"})
    assert _permission_gaps(theirs, frozenset({"item.read", "item.update"})) == []
    assert _permission_gaps(theirs, frozenset({"item.read@own"})) == ["item.update"]
    # @team does not cover a need for @any
    assert _permission_gaps(frozenset({"item.read"}), frozenset({"item.read@team"})) == [
        "item.read"
    ]


async def test_less_privileged_successor_is_refused_naming_the_gap(db):
    admin = await _user(db, "admin", role=InstanceRole.ADMIN)
    leaver = await _user(db, "leaver")
    junior = await _user(db, "junior")
    project = await make_project(db, "SV")
    await _join(db, project, leaver)
    # something to inherit, so the successor is exercised
    await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="handover"), leaver
    )

    gaps = await successor_viability(db, leaver, junior)
    assert [g["label"] for g in gaps] == [project.key]
    assert "item.update" in gaps[0]["missing"]

    with pytest.raises(ConflictError) as refused:
        await auth_service.delete_user(db, leaver.id, junior.id, actor=admin)
    assert project.key in str(refused.value)
    assert "holds less access" in str(refused.value)


async def test_equal_successor_passes_and_access_dies(db):
    admin = await _user(db, "admin", role=InstanceRole.ADMIN)
    leaver = await _user(db, "leaver")
    peer = await _user(db, "peer")
    project = await make_project(db, "SV")
    await _join(db, project, leaver)
    await _join(db, project, peer)
    item = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="handover"), leaver
    )

    assert await successor_viability(db, leaver, peer) == []
    await auth_service.delete_user(db, leaver.id, peer.id, actor=admin)

    # content moved …
    reporter = (
        await db.execute(
            text("SELECT reporter_id FROM work_items WHERE id = :id"), {"id": item.id}
        )
    ).scalar()
    assert reporter == peer.id
    # … access did NOT: the peer keeps their OWN project grant and only that one
    # (RADD-929 — project membership is a project-scoped role grant).
    memberships = (
        await db.execute(
            text(
                "SELECT count(*) FROM global_role_grants "
                "WHERE user_id = :u AND project_id IS NOT NULL"
            ),
            {"u": peer.id},
        )
    ).scalar()
    assert memberships == 1
    leftovers = (
        await db.execute(
            text(
                "SELECT count(*) FROM global_role_grants WHERE user_id = :u UNION ALL "
                "SELECT count(*) FROM team_members WHERE user_id = :u"
            ),
            {"u": leaver.id},
        )
    ).scalars()
    assert all(count == 0 for count in leftovers)


async def test_admin_leaver_needs_admin_successor(db):
    admin = await _user(db, "admin", role=InstanceRole.ADMIN)
    second_admin = await _user(db, "second", role=InstanceRole.ADMIN)
    plain = await _user(db, "plain")

    gaps = await successor_viability(db, second_admin, plain)
    assert gaps == [
        {
            "scope_type": "instance",
            "label": "instance",
            "scope_id": None,
            "missing": ["instance administrator"],
        }
    ]
    assert await successor_viability(db, second_admin, admin) == []
    # and an admin successor is viable for anyone
    assert await successor_viability(db, plain, admin) == []
