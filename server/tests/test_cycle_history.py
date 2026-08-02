"""Item↔cycle stint history (spec 56) — the cross-module contract many surfaces
rely on: items service records stints on every cycle change, hydration exposes
the closed ones as `past_cycles`, and SLQ `past_cycle` finds carryovers.

Rolled-back transactions against the compose Postgres (same as the other
service-level suites)."""

import uuid
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.cycles import service as cycles_service
from radd.modules.cycles.models import ItemCycleRecord
from radd.modules.cycles.schemas import CycleCreate
from radd.modules.items import service as items_service
from radd.modules.items.filters import ItemListFilters
from radd.modules.items.schemas import ItemCreate, ItemUpdate
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


@pytest.fixture
async def admin(db) -> User:
    user = User(
        email=f"ch-{uuid.uuid4().hex[:8]}@example.com",
        name="Cycle History Admin",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _records(db, item_id):
    rows = await db.execute(
        select(ItemCycleRecord)
        .where(ItemCycleRecord.item_id == item_id)
        .order_by(ItemCycleRecord.added_at.asc(), ItemCycleRecord.removed_at.asc().nulls_last())
    )
    return list(rows.scalars())


async def test_cycle_stints_record_and_query(db, admin):
    project = await projects_service.create_project(
        db, ProjectCreate(key="CHX", name="Cycle Hist X")
    )
    today = date(2026, 7, 21)
    first = await cycles_service.create_cycle(
        db, CycleCreate(name="CH - 1"), today, actor_id=admin.id
    )
    second = await cycles_service.create_cycle(
        db, CycleCreate(name="CH - 2"), today, actor_id=admin.id
    )

    # Created in a cycle -> one OPEN stint.
    item = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="carryover", cycle_id=first.id), admin
    )
    records = await _records(db, item.id)
    assert [(r.cycle_id, r.removed_at is None) for r in records] == [(first.id, True)]

    # The carryover move (what complete-cycle does): old stint closes, new opens.
    await items_service.update_item(db, item.id, ItemUpdate(cycle_id=second.id), actor=admin)
    records = await _records(db, item.id)
    assert [(r.cycle_id, r.removed_at is None) for r in records] == [
        (first.id, False),
        (second.id, True),
    ]

    # Hydration: the CLOSED stint is the past; the open one stays `cycle`.
    read = await items_service.get_item(db, item.id, actor=admin)
    assert [c.name for c in read.past_cycles] == ["CH - 1"]
    assert read.cycle is not None and read.cycle.name == "CH - 2"

    # SLQ: past_cycle finds the carryover; the CURRENT cycle is not "past".
    async def matches(q: str) -> set[uuid.UUID]:
        reads = await items_service.list_items(
            db, actor=admin, filters=ItemListFilters(project_id=project.id),
            q=q, limit=50, offset=0,
        )
        return {r.id for r in reads}

    assert item.id in await matches('past_cycle = "CH - 1"')
    assert item.id not in await matches('past_cycle = "CH - 2"')
    assert item.id in await matches("past_cycle IS NOT EMPTY")

    # Clearing the cycle closes the stint; no open rows remain.
    await items_service.update_item(db, item.id, ItemUpdate(cycle_id=None), actor=admin)
    records = await _records(db, item.id)
    assert all(r.removed_at is not None for r in records)
    # Re-entering opens a SECOND stint for the same cycle (visits, not membership) —
    # and past_cycles stays deduped.
    await items_service.update_item(db, item.id, ItemUpdate(cycle_id=first.id), actor=admin)
    records = await _records(db, item.id)
    assert len([r for r in records if r.cycle_id == first.id]) == 2
    read = await items_service.get_item(db, item.id, actor=admin)
    assert [c.name for c in read.past_cycles] == ["CH - 1", "CH - 2"]
