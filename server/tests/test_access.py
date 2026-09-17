"""The generic access-grant framework (spec 92) — service CRUD + validation.

DB-backed but never committed (rolls back on close). The pure resolution is
covered by test_field_grants; this pins the storage layer: subject/access/scope
validation, dedup, batch loading, and clear-on-delete.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import ConflictError
import radd.modules.fields.service  # noqa: F401 — registers the "field" resource on import
from radd.modules.access import service as access
from radd.modules.access.types import Access, GrantSubject
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.teams import service as teams_service
from radd.modules.teams.schemas import TeamCreate

FIELD = "field"  # registered by the fields module on import


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _team(db, name="Leads"):
    return await teams_service.create_team(db, TeamCreate(name=f"{name}-{uuid.uuid4().hex[:6]}"))


async def _project(db):
    return await projects_service.create_project(
        db, ProjectCreate(key=f"AC{uuid.uuid4().hex[:6].upper()}", name="Access")
    )


async def test_add_scoped_grant_and_list(db):
    team = await _team(db)
    project = await _project(db)
    resource_id = str(uuid.uuid4())
    grant = await access.add_grant(
        db, FIELD, resource_id,
        subject_type=GrantSubject.TEAM, subject_id=team.id,
        access=Access.READ.value, project_id=project.id,
    )
    assert grant.project_id == project.id
    rows = await access.list_for_resource(db, FIELD, resource_id)
    assert [r.id for r in rows] == [grant.id]


async def test_duplicate_guarded_including_global(db):
    team = await _team(db)
    rid = str(uuid.uuid4())
    await access.add_grant(
        db, FIELD, rid, subject_type=GrantSubject.TEAM, subject_id=team.id, access=Access.READ.value
    )
    with pytest.raises(ConflictError):
        await access.add_grant(
            db, FIELD, rid, subject_type=GrantSubject.TEAM, subject_id=team.id, access=Access.READ.value
        )


async def test_unknown_resource_type_rejected(db):
    team = await _team(db)
    with pytest.raises(ConflictError):
        await access.add_grant(
            db, "nope", "x", subject_type=GrantSubject.TEAM, subject_id=team.id, access="read"
        )


async def test_unknown_subject_rejected(db):
    with pytest.raises(ConflictError):
        await access.add_grant(
            db, FIELD, "x", subject_type=GrantSubject.TEAM, subject_id=uuid.uuid4(), access=Access.READ.value
        )


async def test_unknown_access_rejected(db):
    team = await _team(db)
    with pytest.raises(ConflictError):
        await access.add_grant(
            db, FIELD, "x", subject_type=GrantSubject.TEAM, subject_id=team.id, access="admin"
        )


async def test_batch_and_clear(db):
    team = await _team(db)
    r1, r2 = str(uuid.uuid4()), str(uuid.uuid4())
    await access.add_grant(db, FIELD, r1, subject_type=GrantSubject.TEAM, subject_id=team.id, access=Access.READ.value)
    await access.add_grant(db, FIELD, r2, subject_type=GrantSubject.TEAM, subject_id=team.id, access=Access.WRITE.value)
    batch = await access.grants_for_resources(db, FIELD, [r1, r2, "empty"])
    assert len(batch[r1]) == 2 and len(batch[r2]) == 2 and batch["empty"] == []
    assert batch[r1][-1].subject_type == "restriction"
    await access.clear_resource(db, FIELD, r1)
    assert await access.list_for_resource(db, FIELD, r1) == []
    assert len(await access.list_for_resource(db, FIELD, r2)) == 1
