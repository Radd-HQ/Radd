"""Multi-project field scope (spec 90 follow-up).

Field scope moved from a single `project_id` to a `field_definition_projects`
association: NO rows = global, rows = scoped to those projects, and a field's
scope can be widened later (add a project) or promoted to global (clear rows).
`definitions_for_project` is the one choke point every consumer resolves through,
so it's what these tests pin. DB-backed but never committed — the session rolls
back on close, so nothing leaks into the dev DB.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.fields import service as fields_service
from radd.modules.fields.schemas import FieldDefinitionCreate, FieldDefinitionUpdate
from radd.modules.fields.types import FieldType
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()  # discard everything this test flushed
    await engine.dispose()


async def _project(db, name: str):
    return await projects_service.create_project(
        db, ProjectCreate(key=f"FS{uuid.uuid4().hex[:6].upper()}", name=name)
    )


def _keys(defs) -> set[str]:
    return {d.key for d in defs}


async def test_scope_resolution_global_single_and_multi(db):
    a = await _project(db, "Alpha")
    b = await _project(db, "Beta")
    tag = uuid.uuid4().hex[:6]

    await fields_service.create_field(
        db, FieldDefinitionCreate(project_ids=[], key=f"g_{tag}", name="Global", type=FieldType.TEXT)
    )
    await fields_service.create_field(
        db, FieldDefinitionCreate(project_ids=[a.id], key=f"a_{tag}", name="OnlyA", type=FieldType.TEXT)
    )
    await fields_service.create_field(
        db,
        FieldDefinitionCreate(
            project_ids=[a.id, b.id], key=f"ab_{tag}", name="AandB", type=FieldType.TEXT
        ),
    )

    in_a = _keys(await fields_service.definitions_for_project(db, a))
    in_b = _keys(await fields_service.definitions_for_project(db, b))
    # Global is in both; the A-only field only in A; the shared field in both.
    assert {f"g_{tag}", f"a_{tag}", f"ab_{tag}"} <= in_a
    assert f"g_{tag}" in in_b and f"ab_{tag}" in in_b
    assert f"a_{tag}" not in in_b
    batch = await fields_service.definitions_for_projects(db, [a.id, b.id])
    assert _keys(batch[a.id]) == in_a
    assert _keys(batch[b.id]) == in_b


async def test_widen_then_promote_to_global(db):
    a = await _project(db, "Alpha")
    b = await _project(db, "Beta")
    tag = uuid.uuid4().hex[:6]
    field = await fields_service.create_field(
        db, FieldDefinitionCreate(project_ids=[a.id], key=f"s_{tag}", name="Scoped", type=FieldType.TEXT)
    )
    fid = field.id
    assert f"s_{tag}" not in _keys(await fields_service.definitions_for_project(db, b))

    # Widen: add project B.
    await fields_service.update_field(
        db, fid, FieldDefinitionUpdate(project_ids=[a.id, b.id]), actor_id=None
    )
    assert f"s_{tag}" in _keys(await fields_service.definitions_for_project(db, b))

    # Promote to global: clear the scope → visible in a brand-new project too.
    await fields_service.update_field(db, fid, FieldDefinitionUpdate(project_ids=[]), actor_id=None)
    c = await _project(db, "Gamma")
    assert f"s_{tag}" in _keys(await fields_service.definitions_for_project(db, c))


async def test_omitted_project_ids_leaves_scope_unchanged(db):
    a = await _project(db, "Alpha")
    tag = uuid.uuid4().hex[:6]
    field = await fields_service.create_field(
        db, FieldDefinitionCreate(project_ids=[a.id], key=f"u_{tag}", name="Unchanged", type=FieldType.TEXT)
    )
    fid = field.id
    # A presentation-only edit (no project_ids key) must not touch the scope.
    await fields_service.update_field(db, fid, FieldDefinitionUpdate(name="Renamed"), actor_id=None)
    reloaded = await fields_service.get_field(db, fid)
    assert reloaded.project_ids == [a.id]
