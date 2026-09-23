"""RADD-1091: `GET /fields` on a project-less instance.

`readable_projects` is per-project, so with no projects it is empty for every
user, admin included. The list gate once refused on that alone, and a fresh
install's admin created a field and watched the list stay empty. The gate now
falls back to the global `field.manage` atom (`fields/router.py`); this pins
the HTTP behaviour on both sides of it.
"""

import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.app import create_app
from radd.config import settings
from radd.db import get_session
from radd.modules.auth import authz, service as auth
from radd.modules.auth.schemas import UserCreate
from radd.modules.auth.types import SESSION_COOKIE_NAME, InstanceRole
from radd.modules.auth.types import LoginMethod


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _person(db, role: InstanceRole):
    return await auth.create_user(
        db,
        UserCreate(
            email=f"fl-{uuid.uuid4().hex[:8]}@people.example.com",
            name="Someone",
            password=f"pw-{uuid.uuid4().hex}",
            instance_role=role,
        ),
    )


async def test_admin_sees_the_field_it_created_with_zero_projects(db, monkeypatch):
    # The shared test database holds projects other files created; a
    # project-less instance is modelled at the seam the gate consults.
    async def no_projects(session, user):
        return {}

    monkeypatch.setattr(authz, "readable_projects", no_projects)

    admin = await _person(db, InstanceRole.ADMIN)
    member = await _person(db, InstanceRole.MEMBER)
    admin_cookie = await auth.create_session(db, admin, method=LoginMethod.PASSWORD)
    member_cookie = await auth.create_session(db, member, method=LoginMethod.PASSWORD)

    async def session_override():
        yield db

    app = create_app()
    app.dependency_overrides[get_session] = session_override
    transport = httpx.ASGITransport(app=app)
    key = f"fl_{uuid.uuid4().hex[:8]}"

    async with httpx.AsyncClient(transport=transport, base_url="http://test", cookies={SESSION_COOKIE_NAME: admin_cookie}) as client:
        created = await client.post("/api/v1/fields", json={"key": key, "name": "Severity", "type": "text"})
        assert created.status_code == 201, created.text
        listed = await client.get("/api/v1/fields")
        assert listed.status_code == 200, listed.text
        assert key in {field["key"] for field in listed.json()}

    for k in list(db.info):  # per-request permission memos (the override shares one session)
        if k.startswith("radd."):
            db.info.pop(k)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", cookies={SESSION_COOKIE_NAME: member_cookie}) as client:
        listed = await client.get("/api/v1/fields")
        assert listed.status_code == 200, listed.text
        assert listed.json() == []
