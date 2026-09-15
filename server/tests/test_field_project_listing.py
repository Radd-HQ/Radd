"""RADD-1158: `GET /fields?project_id=` returns the fields IN SCOPE for that project.

The New Item form used to load the whole registry and render every definition,
so a field scoped to project A appeared on the create form for project B, where
the server's scope validation then rejected the value — edit-then-error, the
class spec 96 exists to prevent. The list route now narrows through the same
predicate `definitions_for_project` resolves with, and the modal asks for it.
This pins the HTTP behaviour against a real scoped field: global + own-scope in,
another project's field out, the count header agreeing, an unknown project 404.
"""

import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.apitypes import TOTAL_COUNT_HEADER
from radd.app import create_app
from radd.config import settings
from radd.db import get_session
from radd.modules.auth import service as auth
from radd.modules.auth.schemas import UserCreate
from radd.modules.auth.types import SESSION_COOKIE_NAME, InstanceRole
from radd.modules.fields.types import FieldType
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _project(db, name: str):
    return await projects_service.create_project(
        db, ProjectCreate(key=f"FP{uuid.uuid4().hex[:6].upper()}", name=name)
    )


async def test_project_id_narrows_the_listing_to_the_scoped_set(db):
    admin = await auth.create_user(
        db,
        UserCreate(
            email=f"fp-{uuid.uuid4().hex[:8]}@people.example.com",
            name="Field admin",
            password=f"pw-{uuid.uuid4().hex}",
            instance_role=InstanceRole.ADMIN,
        ),
    )
    cookie = await auth.create_session(db, admin)
    a = await _project(db, "Alpha")
    b = await _project(db, "Beta")
    tag = uuid.uuid4().hex[:6]

    async def session_override():
        yield db

    app = create_app()
    app.dependency_overrides[get_session] = session_override
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", cookies={SESSION_COOKIE_NAME: cookie}
    ) as client:
        for key, project_ids in ((f"g_{tag}", []), (f"a_{tag}", [str(a.id)])):
            created = await client.post(
                "/api/v1/fields",
                json={"key": key, "name": key, "type": FieldType.TEXT, "project_ids": project_ids},
            )
            assert created.status_code == 201, created.text

        in_a = await client.get("/api/v1/fields", params={"project_id": str(a.id)})
        assert in_a.status_code == 200, in_a.text
        keys_a = {f["key"] for f in in_a.json()}
        assert {f"g_{tag}", f"a_{tag}"} <= keys_a

        in_b = await client.get("/api/v1/fields", params={"project_id": str(b.id)})
        assert in_b.status_code == 200, in_b.text
        keys_b = {f["key"] for f in in_b.json()}
        assert f"g_{tag}" in keys_b
        assert f"a_{tag}" not in keys_b

        # The unscoped registry still carries both — scope is a narrowing, not a hiding.
        everything = await client.get("/api/v1/fields")
        assert {f"g_{tag}", f"a_{tag}"} <= {f["key"] for f in everything.json()}

        # Paged: the count header agrees with the scoped set, and `q` composes with it.
        paged = await client.get(
            "/api/v1/fields", params={"project_id": str(b.id), "q": tag, "limit": 50}
        )
        assert paged.status_code == 200, paged.text
        assert {f["key"] for f in paged.json()} == {f"g_{tag}"}
        assert paged.headers[TOTAL_COUNT_HEADER] == "1"

        missing = await client.get("/api/v1/fields", params={"project_id": str(uuid.uuid4())})
        assert missing.status_code == 404, missing.text
