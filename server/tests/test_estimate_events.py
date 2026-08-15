"""RADD-1102 — estimate edits emit; other clients' boards finally react.

The SPA's `item_estimate` realtime mapping existed with no event that could
reach it: set/clear_estimate wrote the row and told nobody.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.events.models import Event
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.timelogging import enablement, service as timelogging
from radd.modules.timelogging.schemas import EstimateSet
from radd.modules.timelogging.types import TimelogEntity, WorklogEvent


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def test_set_and_clear_emit_under_item_estimate(db):
    admin = User(
        email=f"est-{uuid.uuid4().hex[:8]}@example.com",
        name="Estimator",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(admin)
    await db.flush()
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"ES{uuid.uuid4().hex[:4].upper()}", name="Est P"),
        actor_id=admin.id,
    )
    await enablement.set_enabled(db, project.id, True)
    item = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="sized work"), actor=admin
    )

    await timelogging.set_estimate(db, item.id, EstimateSet(estimate="2h"), actor_id=admin.id)
    await timelogging.clear_estimate(db, item.id, actor_id=admin.id)

    rows = (
        (
            await db.execute(
                select(Event)
                .where(
                    Event.event_type == WorklogEvent.ESTIMATE_CHANGED.value,
                    Event.entity_id == str(item.id),
                )
                .order_by(Event.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert all(r.entity_type == TimelogEntity.ITEM_ESTIMATE.value for r in rows)
    assert rows[0].payload["original_estimate_seconds"] == 2 * 3600
    assert rows[1].payload["original_estimate_seconds"] is None
    assert all(str(r.actor_id) == str(admin.id) for r in rows)
