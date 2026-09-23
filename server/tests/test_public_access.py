"""Spec 121 §1 (RADD-1144): the project's public-access switches ARE two grants.

`PUT /projects/{id}/public-access` writes the Public role to Anyone and the
Contributor role to Signed-in users, `GET /projects` reports them as
`public` / `contributions`, and the world's reads follow the rows exactly.
"""

import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.modules.auth import grants, principals, public_access, roles, service as auth
from radd.modules.auth.models import GlobalRoleGrant
from radd.modules.auth.schemas import UserCreate
from radd.modules.auth.types import SESSION_COOKIE_NAME, BuiltinRoleKey, InstanceRole
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


async def _person(db, *, role: InstanceRole = InstanceRole.MEMBER):
    return await auth.create_user(
        db,
        UserCreate(
            email=f"pa-{uuid.uuid4().hex[:8]}@people.example.com",
            name="Someone",
            password=f"pw-{uuid.uuid4().hex}",
            instance_role=role,
        ),
    )


async def _project(db):
    return await projects.create_project(
        db, ProjectCreate(key=f"PA{uuid.uuid4().hex[:5].upper()}", name="Switchable")
    )


async def _principal_grants(db, project):
    rows = await db.execute(
        select(GlobalRoleGrant.user_id, GlobalRoleGrant.role_id).where(
            GlobalRoleGrant.project_id == project.id,
            GlobalRoleGrant.user_id.in_([principals.ANYONE_ID, principals.SIGNED_IN_ID]),
        )
    )
    return set(rows.all())


async def test_switches_write_and_remove_the_two_grants(db):
    project = await _project(db)
    public_role = await roles.role_by_key(db, BuiltinRoleKey.PUBLIC.value)
    contributor = await roles.role_by_key(db, BuiltinRoleKey.CONTRIBUTOR.value)
    assert await public_access.public_access(db, project.id) == public_access.PublicAccess()

    await public_access.set_public_access(db, project, public=True, contributions=True, actor_id=None)
    assert await _principal_grants(db, project) == {
        (principals.ANYONE_ID, public_role.id),
        (principals.SIGNED_IN_ID, contributor.id),
    }
    assert await public_access.public_access(db, project.id) == public_access.PublicAccess(
        public=True, contributions=True
    )
    # Idempotent: flipping to the same state writes nothing new.
    await public_access.set_public_access(db, project, public=True, contributions=True, actor_id=None)
    assert len(await _principal_grants(db, project)) == 2

    await public_access.set_public_access(db, project, public=False, contributions=False, actor_id=None)
    assert await _principal_grants(db, project) == set()


async def test_contributions_need_a_public_project(db):
    from radd.exceptions import ConflictError

    project = await _project(db)
    with pytest.raises(ConflictError, match="public"):
        await public_access.set_public_access(db, project, public=False, contributions=True, actor_id=None)


async def test_http_switches_are_the_grants_the_world_reads_by(db):
    from radd.app import create_app
    from radd.db import get_session

    project = await _project(db)
    admin = await _person(db, role=InstanceRole.ADMIN)
    outsider = await _person(db)
    admin_cookie = await auth.create_session(db, admin, method=LoginMethod.PASSWORD)
    outsider_cookie = await auth.create_session(db, outsider, method=LoginMethod.PASSWORD)

    async def session_override():
        yield db

    app = create_app()
    app.dependency_overrides[get_session] = session_override
    transport = httpx.ASGITransport(app=app)
    path = f"/api/v1/projects/{project.id}/public-access"

    async with httpx.AsyncClient(transport=transport, base_url="http://test", cookies={SESSION_COOKIE_NAME: outsider_cookie}) as client:
        refused = await client.put(path, json={"public": True, "contributions": True})
        assert refused.status_code == 403, refused.text

    async with httpx.AsyncClient(transport=transport, base_url="http://test", cookies={SESSION_COOKIE_NAME: admin_cookie}) as client:
        flipped = await client.put(path, json={"public": True, "contributions": True})
        assert flipped.status_code == 200, flipped.text
        assert flipped.json()["public"] is True and flipped.json()["contributions"] is True
        listed = await client.get("/api/v1/projects", params={"ids": str(project.id)})
        assert listed.json()[0]["public"] is True

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        world = await client.get(f"/api/v1/projects/{project.id}")
        assert world.status_code == 200, world.text
        assert world.json()["public"] is True

    async with httpx.AsyncClient(transport=transport, base_url="http://test", cookies={SESSION_COOKIE_NAME: admin_cookie}) as client:
        closed = await client.put(path, json={"public": False, "contributions": False})
        assert closed.status_code == 200 and closed.json()["public"] is False
        rows = await grants.grants_for_project(db, project.id)
        assert not [g for g in rows if g.user_id in principals.PRINCIPAL_IDS]

    # The override shares ONE session across requests, so drop the per-request
    # permission memos the earlier anonymous read left behind (production gets
    # a fresh session per request).
    for key in list(db.info):
        if key.startswith("radd."):
            db.info.pop(key)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get(f"/api/v1/projects/{project.id}")).status_code in (403, 404)
