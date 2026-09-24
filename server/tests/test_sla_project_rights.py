"""RADD-1303 — a project's Manager manages its SLA policies, and nobody else's.

SLA policies belong to a project (spec 67); their atoms were global, so only
instance admins could touch them. Now they are project-scoped under
project.manage: the Manager role on project A may create/edit/delete A's
policies and is refused on B's.
"""

import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.app import create_app
from radd.config import settings
from radd.db import get_session
from radd.modules.auth import roles
from radd.modules.auth import service as auth_service
from radd.modules.auth.models import GlobalRoleGrant, Role, User
from radd.modules.auth.types import SESSION_COOKIE_NAME, BuiltinRoleKey, LoginMethod, expand_permissions
from radd.modules.projects import service as projects
from radd.modules.projects.schemas import ProjectCreate


def test_sla_rights_are_project_rights_under_project_manage():
    held = expand_permissions({"project.manage"})
    assert {"sla.create", "sla.update", "sla.delete"} <= held
    assert "sla.update" not in expand_permissions({"global.manage"})


@pytest.fixture
async def world():
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        await roles.ensure_builtin_roles(db)
        manager_role = await db.scalar(select(Role).where(Role.key == BuiltinRoleKey.MANAGER.value))
        person = User(email=f"slr-{uuid.uuid4().hex[:8]}@example.com", name="Project manager", instance_role="member")
        db.add(person)
        await db.flush()
        mine = await projects.create_project(db, ProjectCreate(key=f"SR{uuid.uuid4().hex[:3].upper()}", name="Mine"))
        theirs = await projects.create_project(db, ProjectCreate(key=f"ST{uuid.uuid4().hex[:3].upper()}", name="Theirs"))
        db.add(GlobalRoleGrant(role_id=manager_role.id, user_id=person.id, project_id=mine.id))
        await db.flush()
        app = create_app()

        async def override():
            yield db

        app.dependency_overrides[get_session] = override
        token = await auth_service.create_session(db, person, method=LoginMethod.PASSWORD_TOTP)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test/api/v1",
                                     cookies={SESSION_COOKIE_NAME: token}) as client:
            yield client, mine, theirs
        await db.rollback()
    await engine.dispose()


async def test_the_manager_manages_their_projects_slas_only(world):
    client, mine, theirs = world
    created = await client.post("/sla-policies", json={"project_id": str(mine.id), "name": "Mine", "response_minutes": 60})
    assert created.status_code == 201, created.text
    policy_id = created.json()["id"]
    edited = await client.patch(f"/sla-policies/{policy_id}", json={"response_minutes": 120})
    assert edited.status_code == 200 and edited.json()["response_minutes"] == 120
    refused = await client.post("/sla-policies", json={"project_id": str(theirs.id), "name": "Theirs", "response_minutes": 60})
    assert refused.status_code in (403, 404)
    deleted = await client.delete(f"/sla-policies/{policy_id}")
    assert deleted.status_code == 204
