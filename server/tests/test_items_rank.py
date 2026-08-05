"""Manual ranking (spec 24) — the rebalance backstop (RADD-878).

_rebalance_ranks used to issue one UPDATE per work item, instance-wide, inside
the user's drag request (503k statements on the perf dataset). Now it is one
set-based statement; these tests pin that the respace preserves order and that
the drag path recovers from a collapsed float gap end-to-end.

DB-backed, flushed, never committed — the session rolls back at teardown.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.items import service as items
from radd.modules.items.models import WorkItem
from radd.modules.items.schemas import ItemCreate, ItemRankUpdate
from radd.modules.items.service.queries import _rebalance_ranks
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
        email=f"rank-{uuid.uuid4().hex[:8]}@example.com",
        name="Rank Tester",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _three_items(db, actor):
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"RK{uuid.uuid4().hex[:4].upper()}", name="Rank")
    )
    made = []
    for title in ("a", "b", "c"):
        made.append(await items.create_item(db, ItemCreate(project_id=project.id, title=title), actor))
    return made


async def _rank_of(db, item_id) -> float:
    return (await db.execute(select(WorkItem.rank).where(WorkItem.id == item_id))).scalar_one()


async def test_rebalance_respaces_in_rank_order(db, actor):
    a, b, c = await _three_items(db, actor)
    # Collapse the gap between a and b to below float resolution.
    for item_id, rank in ((a.id, 1.0), (b.id, 1.0 + 1e-13), (c.id, 2.0)):
        obj = await db.get(WorkItem, item_id)
        obj.rank = rank
    await db.flush()

    await _rebalance_ranks(db)

    ra, rb, rc = [await _rank_of(db, x.id) for x in (a, b, c)]
    step = config.item_rank_step
    # Order preserved, gaps restored to full steps.
    assert ra < rb < rc
    assert rb - ra == pytest.approx(step)
    assert rc - rb == pytest.approx(step)
    assert ra % step == pytest.approx(0.0)


async def test_reorder_recovers_from_collapsed_gap(db, actor):
    a, b, c = await _three_items(db, actor)
    for item_id, rank in ((a.id, 1.0), (b.id, 1.0 + 1e-13), (c.id, 2.0)):
        obj = await db.get(WorkItem, item_id)
        obj.rank = rank
    await db.flush()

    # Drag c between a and b — the midpoint of a collapsed pair forces the respace.
    await items.reorder_item(db, c.id, ItemRankUpdate(after_id=a.id, before_id=b.id), actor)

    ra, rb, rc = [await _rank_of(db, x.id) for x in (a, b, c)]
    assert ra < rc < rb
