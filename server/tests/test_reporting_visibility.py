"""RADD-1150: reports fold over the same row filter as the lists, so a report's
numbers match what the reader can list — for the world included.

The spec-121 visibility fixture (a public, an internal and a restricted issue,
all moved to done, on a PUBLIC project) reported by three readers:

| reader                       | throughput | cumulative flow (done) |
|------------------------------|------------|------------------------|
| the world (Anyone)           | 1          | 1                      |
| a member (unqualified read)  | 2          | 2                      |
| an instance admin            | 3          | 3                      |
"""

import uuid
from datetime import date, timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.modules.auth import grants, principals, roles, service as auth
from radd.modules.auth.models import Role, User
from radd.modules.auth.schemas import UserCreate
from radd.modules.auth.types import SESSION_COOKIE_NAME, BuiltinRoleKey, InstanceRole
from radd.modules.items import service as items
from radd.modules.items.enums import ItemVisibility
from radd.modules.items.schemas import ItemCreate, ItemUpdate
from radd.modules.projects import service as projects
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.reporting import service as reporting
from radd.modules.reporting.types import ReportInterval
from radd.modules.workflow import service as workflow
from radd.modules.workflow.types import StateCategory


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


async def _person(db, name: str, *, role: InstanceRole = InstanceRole.MEMBER) -> User:
    return await auth.create_user(
        db,
        UserCreate(
            email=f"{name}-{uuid.uuid4().hex[:8]}@people.example.com",
            name=name,
            password=f"pw-{uuid.uuid4().hex}",
            instance_role=role,
        ),
    )


def _forget(db):
    for key in list(db.info):
        if key.startswith("radd."):
            db.info.pop(key)


@pytest.fixture
async def world(db):
    admin = await _person(db, "admin", role=InstanceRole.ADMIN)
    member = await _person(db, "member")
    project = await projects.create_project(
        db, ProjectCreate(key=f"RV{uuid.uuid4().hex[:6].upper()}", name="Report visibility")
    )
    public_role = await roles.role_by_key(db, BuiltinRoleKey.PUBLIC.value)
    await grants.create_grant(
        db, public_role.id, user_id=principals.ANYONE_ID, project_id=project.id
    )
    reader = Role(key=f"reader-{uuid.uuid4().hex[:6]}", name="reader", permissions=["item.read"])
    db.add(reader)
    await db.flush()
    await grants.create_grant(db, reader.id, user_id=member.id, project_id=project.id)
    done = next(
        s for s in await workflow.list_states(db, project.id) if s.category == StateCategory.DONE.value
    )
    for level in ItemVisibility:
        item = await items.create_item(
            db, ItemCreate(project_id=project.id, title=f"{level.value} done", visibility=level), admin
        )
        await items.update_item(db, item.id, ItemUpdate(state_id=done.id), admin)
    anyone = await db.get(User, principals.ANYONE_ID)
    return {"project": project, "admin": admin, "member": member, "anyone": anyone}


EXPECTED = {"anyone": 1, "member": 2, "admin": 3}


@pytest.mark.parametrize("who", sorted(EXPECTED))
async def test_throughput_and_flow_match_what_the_reader_can_list(db, world, who):
    actor, project = world[who], world["project"]
    _forget(db)
    start, end = date.today() - timedelta(days=1), date.today()
    rows = await reporting.throughput(db, project.id, start, end, ReportInterval.DAY, actor=actor)
    assert sum(row.count for row in rows) == EXPECTED[who], who
    flow = await reporting.cumulative_flow(db, project.id, start, end, ReportInterval.DAY, actor=actor)
    assert flow[-1].counts[StateCategory.DONE.value] == EXPECTED[who], who


async def test_http_the_world_reads_a_public_projects_reports(db, world):
    from radd.app import create_app
    from radd.db import get_session

    project = world["project"]
    private = await projects.create_project(
        db, ProjectCreate(key=f"RP{uuid.uuid4().hex[:6].upper()}", name="Private")
    )
    member_cookie = await auth.create_session(db, world["member"])

    async def session_override():
        yield db

    app = create_app()
    app.dependency_overrides[get_session] = session_override
    transport = httpx.ASGITransport(app=app)
    window = {"start": (date.today() - timedelta(days=1)).isoformat(), "end": date.today().isoformat()}
    _forget(db)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/v1/reports/throughput", params={"project_id": str(project.id), **window})
        assert r.status_code == 200, r.text
        assert sum(row["count"] for row in r.json()) == 1
        assert (await client.get("/api/v1/reports/time-in-state", params={"project_id": str(project.id)})).status_code == 200
        assert (await client.get("/api/v1/reports/sla", params={"project_id": str(project.id)})).status_code == 200
        assert (await client.get("/api/v1/reports/velocity")).status_code == 200
        refused = await client.get("/api/v1/reports/throughput", params={"project_id": str(private.id), **window})
        assert refused.status_code in (403, 404), refused.text
    _forget(db)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", cookies={SESSION_COOKIE_NAME: member_cookie}
    ) as client:
        r = await client.get("/api/v1/reports/throughput", params={"project_id": str(project.id), **window})
        assert sum(row["count"] for row in r.json()) == 2
