"""User-definable issue link types (spec 91).

The catalog is the single source of truth for what relationships exist, their
directional names, symmetry, and scope. DB-backed but never committed — the
session rolls back on close, so nothing leaks into the dev DB (the built-ins are
already seeded there).
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import ConflictError
from radd.modules.linktypes import service as lt
from radd.modules.linktypes.schemas import LinkTypeCreate, LinkTypeUpdate
from radd.modules.linktypes.types import LinkDirection
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
        db, ProjectCreate(key=f"LT{uuid.uuid4().hex[:6].upper()}", name=name)
    )


async def test_builtins_present_and_symmetry(db):
    catalog = await lt.catalog(db)
    assert {"blocks", "relates", "duplicates", "mentions"} <= set(catalog)
    assert lt.is_symmetric(catalog, "relates") is True
    assert lt.is_symmetric(catalog, "blocks") is False
    assert lt.is_auto_managed(catalog, "mentions") is True
    assert lt.is_auto_managed(catalog, "blocks") is False
    # Directional labels resolve per edge.
    assert lt.label_for(catalog["blocks"], incoming=False) == "blocks"
    assert lt.label_for(catalog["blocks"], incoming=True) == "is blocked by"


async def test_create_scoped_type_and_project_resolution(db):
    a = await _project(db, "Alpha")
    b = await _project(db, "Beta")
    key = f"dep_{uuid.uuid4().hex[:6]}"
    created = await lt.create_type(
        db,
        LinkTypeCreate(
            key=key, name="Depends", outward_name="depends on", inward_name="is required for",
            direction=LinkDirection.DIRECTED, project_ids=[a.id],
        ),
    )
    assert created.project_ids == [a.id]
    a_keys = {t.key for t in await lt.types_for_project(db, a.id)}
    b_keys = {t.key for t in await lt.types_for_project(db, b.id)}
    # Scoped to A only; built-ins (global) show in both; mentions (auto) excluded.
    assert key in a_keys and key not in b_keys
    assert "blocks" in a_keys and "blocks" in b_keys
    assert "mentions" not in a_keys


async def test_symmetric_type_mirrors_inward_name(db):
    key = f"twin_{uuid.uuid4().hex[:6]}"
    created = await lt.create_type(
        db,
        LinkTypeCreate(key=key, name="Twins", outward_name="twins with",
                       inward_name="whatever", direction=LinkDirection.SYMMETRIC),
    )
    assert created.inward_name == "twins with"  # symmetric → inward mirrors outward


async def test_delete_guards(db):
    # A built-in can't be deleted.
    builtin = await lt.by_key(db, "blocks")
    with pytest.raises(ConflictError):
        await lt.delete_type(db, builtin.id)
    # A fresh custom type with no usages can be.
    key = f"tmp_{uuid.uuid4().hex[:6]}"
    created = await lt.create_type(db, LinkTypeCreate(key=key, name="Temp", outward_name="temp"))
    await lt.delete_type(db, created.id)
    assert await lt.by_key(db, key) is None


async def test_update_widens_scope_and_locks_builtin_direction(db):
    a = await _project(db, "Alpha")
    key = f"rel_{uuid.uuid4().hex[:6]}"
    created = await lt.create_type(db, LinkTypeCreate(key=key, name="Rel", outward_name="rel"))
    # Widen to project A, then back to global.
    await lt.update_type(db, created.id, LinkTypeUpdate(project_ids=[a.id]))
    assert (await lt.get_type(db, created.id)).project_ids == [a.id]
    await lt.update_type(db, created.id, LinkTypeUpdate(project_ids=[]))
    assert (await lt.get_type(db, created.id)).project_ids == []
    # A built-in's direction is locked.
    builtin = await lt.by_key(db, "blocks")
    with pytest.raises(ConflictError):
        await lt.update_type(db, builtin.id, LinkTypeUpdate(direction=LinkDirection.SYMMETRIC))


async def test_resolve_by_name_for_importer(db):
    key = f"dep_{uuid.uuid4().hex[:6]}"
    await lt.create_type(
        db, LinkTypeCreate(key=key, name="Depends", outward_name="depends on",
                           inward_name="is required for", direction=LinkDirection.DIRECTED)
    )
    # A Jira link-type name matches by any of name/outward/inward.
    assert await lt.resolve_by_name(db, "depends on") == key
    assert await lt.resolve_by_name(db, "Depends") == key
    assert await lt.resolve_by_name(db, "is required for") == key
    assert await lt.resolve_by_name(db, "no such name") is None
