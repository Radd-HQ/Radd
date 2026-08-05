"""Roadmap timelog batch (spec 78): POST /items/timelog/batch — estimate/logged
seconds per readable item (auto-schedule durations), the readable-ids filter,
and the schema-enforced cap.

DB-backed (compose Postgres) — flushed, never committed; the session rolls back
at teardown, so rows never persist.
"""

import uuid
from datetime import date

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.items import service as items
from radd.modules.items.schemas import ItemCreate
from radd.modules.timelogging import service as timelog
from radd.modules.timelogging.models import ItemEstimate, Worklog
from radd.modules.timelogging.schemas import TIMELOG_BATCH_MAX_ITEMS, TimelogBatchRequest
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def actor(db) -> User:
    user = User(
        email=f"tb-{uuid.uuid4().hex[:8]}@example.com",
        name="Timelog Batch Tester",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _project(db, key_prefix="TB"):
    project = await projects_service.create_project(
        db,
        ProjectCreate(
            key=f"{key_prefix}{uuid.uuid4().hex[:4].upper()}",
            name="P",
        ),
    )
    return project


async def test_batch_shape(db, actor):
    project = await _project(db)
    estimated = await items.create_item(
        db, ItemCreate(project_id=project.id, title="Estimated"), actor
    )
    bare = await items.create_item(db, ItemCreate(project_id=project.id, title="Bare"), actor)
    db.add(ItemEstimate(item_id=estimated.id, original_estimate_seconds=7200))
    db.add(
        Worklog(
            item_id=estimated.id,
            author_id=actor.id,
            worked_on=date(2026, 7, 20),
            time_spent_seconds=600,
        )
    )
    db.add(
        Worklog(
            item_id=estimated.id,
            author_id=actor.id,
            worked_on=date(2026, 7, 21),
            time_spent_seconds=300,
        )
    )
    await db.flush()

    # Duplicate + unknown ids: dedup'd, unknown omitted; readable ids ALWAYS
    # appear — None/0 distinguishes "no estimate/logs" from "not allowed".
    result = await timelog.timelog_batch(db, actor, [estimated.id, bare.id, estimated.id, uuid.uuid4()])
    assert set(result) == {estimated.id, bare.id}
    assert result[estimated.id].estimate_seconds == 7200
    assert result[estimated.id].logged_seconds == 900
    assert result[bare.id].estimate_seconds is None
    assert result[bare.id].logged_seconds == 0


async def test_batch_readable_filter(db, actor):
    project = await _project(db)
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="Hidden"), actor)
    # Spec 86: any ACTIVE user reads every project (member floor); only an
    # INACTIVE account's view is empty (mirroring sla/batch/rollup).
    other = User(
        email=f"tb-out-{uuid.uuid4().hex[:8]}@example.com",
        name="Other",
        instance_role=InstanceRole.MEMBER.value,
    )
    inactive = User(
        email=f"tb-in-{uuid.uuid4().hex[:8]}@example.com",
        name="Inactive",
        instance_role=InstanceRole.MEMBER.value,
        active=False,
    )
    db.add_all([other, inactive])
    await db.flush()
    assert set(await timelog.timelog_batch(db, other, [item.id])) == {item.id}
    assert await timelog.timelog_batch(db, inactive, [item.id]) == {}


async def test_batch_cap_is_schema_enforced(db):
    # The batch cap is a shape error — pydantic rejects it (422 at the boundary).
    with pytest.raises(ValidationError):
        TimelogBatchRequest(item_ids=[uuid.uuid4() for _ in range(TIMELOG_BATCH_MAX_ITEMS + 1)])


async def test_item_timelog_endpoint_answers(db, actor):
    """RADD-856: GET /items/{id}/timelog 500'd on the live 0.18.1 — the wave's
    seam conversion dropped the tuple unpack (`project` undefined, a NameError
    no test executed). This calls the ROUTER function itself, so a variable
    slip in the handler can never again ship silently."""
    from radd.modules.timelogging.worklog_router import item_timelog

    project = await projects_service.create_project(
        db, ProjectCreate(key=f"TL{uuid.uuid4().hex[:4].upper()}", name="Rail")
    )
    item = await items.create_item(
        db, ItemCreate(project_id=project.id, title="rail summary"), actor
    )
    summary = await item_timelog(item.id, db, actor)
    assert summary.logged_seconds == 0
