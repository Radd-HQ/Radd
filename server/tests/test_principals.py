"""Spec 121 (RADD-1142): Anyone and Signed-in users are grant subjects.

A public project is the Public role granted to Anyone on that project;
contributions are the Contributor role granted to Signed-in users. Every
actor holds Anyone's grants, every real account holds Signed-in users' too,
and an unauthenticated request acts as the Anyone row — which holds NO floor
of its own.
"""

import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.exceptions import ConflictError, ForbiddenError, UnauthorizedError
from radd.modules.auth import authz, grants, principals, roles, service as auth
from radd.modules.auth.models import User
from radd.modules.auth.schemas import UserCreate
from radd.modules.auth.types import (
    SESSION_COOKIE_NAME,
    BuiltinRoleKey,
    InstanceRole,
    Permission,
    UserSource,
)
from radd.modules.projects import service as projects
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.auth.types import LoginMethod


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        await roles.ensure_builtin_roles(session)
        await principals.ensure_principals(session)
        yield session
        await session.rollback()
    await engine.dispose()


async def _person(db, *, role: InstanceRole = InstanceRole.MEMBER) -> User:
    return await auth.create_user(
        db,
        UserCreate(
            email=f"p-{uuid.uuid4().hex[:8]}@people.example.com",
            name="A Person",
            password=f"pw-{uuid.uuid4().hex}",
            instance_role=role,
        ),
    )


async def _project(db):
    return await projects.create_project(
        db, ProjectCreate(key=f"P{uuid.uuid4().hex[:6].upper()}", name="Maybe public")
    )


async def _grant(db, role_key: BuiltinRoleKey, subject_id: uuid.UUID, project):
    role = await roles.role_by_key(db, role_key.value)
    grant = await grants.create_grant(
        db, role_id=role.id, user_id=subject_id, project_id=project.id, actor_id=None
    )
    return grant


def _forget(db, *user_ids):
    for user_id in user_ids:
        db.info.pop(f"radd.project_permission_map:{user_id}", None)
        db.info.pop(f"radd.readable_projects:{user_id}", None)


async def test_principals_are_seeded_and_cannot_sign_in(db):
    anyone = await db.get(User, principals.ANYONE_ID)
    signed_in = await db.get(User, principals.SIGNED_IN_ID)
    assert anyone is not None and anyone.source == UserSource.PRINCIPAL.value
    assert signed_in is not None and signed_in.active
    with pytest.raises(UnauthorizedError, match="principal"):
        await auth.create_session(db, anyone, method=LoginMethod.PASSWORD)


async def test_anyone_holds_no_floor(db):
    """The Baseline is policy for ACCOUNTS. The world's access is exactly the
    grants written against the principal rows — so with none, nothing."""
    anyone = await db.get(User, principals.ANYONE_ID)
    assert await authz.effective_permissions(db, anyone) == frozenset()
    project = await _project(db)
    assert await authz.effective_permissions(db, anyone, project=project) == frozenset()


async def test_a_public_grant_reaches_everyone(db):
    project = await _project(db)
    await _grant(db, BuiltinRoleKey.PUBLIC, principals.ANYONE_ID, project)
    anyone = await db.get(User, principals.ANYONE_ID)
    person = await _person(db)
    for actor in (anyone, person):
        perms = await authz.effective_permissions(db, actor, project=project)
        assert "item.read@public" in perms, actor.name
        assert Permission.ITEM_READ not in perms  # the world reads public rows only
        assert Permission.COMMENT_READ_INTERNAL not in perms
    # …and the project is OFFERED to both (row-property relation = entitled).
    for actor in (anyone, person):
        _forget(db, actor.id)
        assert project.id in await authz.visible_projects(db, actor), actor.name


async def test_a_contributor_grant_reaches_accounts_but_never_the_world(db):
    project = await _project(db)
    await _grant(db, BuiltinRoleKey.CONTRIBUTOR, principals.SIGNED_IN_ID, project)
    person = await _person(db)
    anyone = await db.get(User, principals.ANYONE_ID)
    assert Permission.ITEM_CREATE in await authz.effective_permissions(db, person, project=project)
    assert Permission.ITEM_CREATE not in await authz.effective_permissions(db, anyone, project=project)


async def test_principals_are_not_people(db):
    """Not an assignee, not a notification target, not in the user directory."""
    from radd.modules.items.service.relations import _resolve_assignee
    from radd.modules.notify.service import mailable_user

    anyone = await db.get(User, principals.ANYONE_ID)
    with pytest.raises((ForbiddenError, ConflictError)):
        await _resolve_assignee(db, principals.ANYONE_ID)
    assert not mailable_user(anyone)
    listed = await auth.list_users(
        db, q="Anyone", sources_excluded=[UserSource.EMAIL, UserSource.PRINCIPAL]
    )
    assert all(u.id != principals.ANYONE_ID for u in listed)


async def test_http_anonymous_reads_exactly_the_public_project(db):
    from radd.app import create_app
    from radd.db import get_session

    public = await _project(db)
    private = await _project(db)
    await _grant(db, BuiltinRoleKey.PUBLIC, principals.ANYONE_ID, public)
    await db.flush()

    async def session_override():
        yield db

    app = create_app()
    app.dependency_overrides[get_session] = session_override
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        me = await client.get("/api/v1/auth/me")
        assert me.status_code == 200, me.text
        assert me.json()["anonymous"] is True
        assert me.json()["id"] == str(principals.ANYONE_ID)

        listed = await client.get("/api/v1/projects")
        assert listed.status_code == 200, listed.text
        keys = {p["key"] for p in listed.json()}
        assert public.key in keys and private.key not in keys

        hidden = await client.get(f"/api/v1/projects/{private.id}")
        assert hidden.status_code in (403, 404), hidden.text

        # A write with no credential is refused at the seam — 401, never 403,
        # never attributed to the principal.
        refused = await client.post(
            "/api/v1/items", json={"project_id": str(public.id), "title": "nope"}
        )
        assert refused.status_code == 401, refused.text

        # The rest of the API still 401s for the world.
        assert (await client.get("/api/v1/notifications")).status_code == 401


async def test_http_a_fresh_account_contributes_only_where_signed_in_users_may(db):
    from radd.app import create_app
    from radd.db import get_session
    from radd.modules.items.models import WorkItem
    from sqlalchemy import select

    public = await _project(db)
    private = await _project(db)
    await _grant(db, BuiltinRoleKey.PUBLIC, principals.ANYONE_ID, public)
    await _grant(db, BuiltinRoleKey.CONTRIBUTOR, principals.SIGNED_IN_ID, public)
    person = await _person(db)
    cookie = await auth.create_session(db, person, method=LoginMethod.PASSWORD)

    async def session_override():
        yield db

    app = create_app()
    app.dependency_overrides[get_session] = session_override
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        cookies={SESSION_COOKIE_NAME: cookie},
    ) as client:
        me = await client.get("/api/v1/auth/me")
        assert me.status_code == 200 and me.json()["anonymous"] is False
        created = await client.post(
            "/api/v1/items", json={"project_id": str(public.id), "title": "From outside"}
        )
        assert created.status_code == 201, created.text
        row = await db.scalar(select(WorkItem).where(WorkItem.id == uuid.UUID(created.json()["id"])))
        assert row is not None and row.reporter_id == person.id
        refused = await client.post(
            "/api/v1/items", json={"project_id": str(private.id), "title": "Not here"}
        )
        assert refused.status_code == 403, refused.text
