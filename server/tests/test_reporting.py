"""Reporting (spec 16): the event-log timeline reconstruction + one report end-to-end.

Like the SLQ suggest tests, everything runs against live Postgres inside a single
rolled-back transaction, so nothing persists. Items are driven through the real
`items.service` so genuine `item.created`/`item.updated` events land in the outbox —
which is exactly what the timeline walk reads back. (`now()` is frozen per transaction
in Postgres, so all events here share a timestamp; the walk orders by the monotonic
event id, not the clock, so segment/transition order is still exact.)
"""

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate, ItemUpdate
from radd.modules.reporting import service as reporting, timeline
from radd.modules.reporting.types import ReportInterval
from radd.modules.workflow import service as workflow
from radd.modules.workflow.models import State
from radd.modules.workflow.types import StateCategory
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project
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
        email=f"rpt-{uuid.uuid4().hex[:8]}@example.com",
        name="Report Admin",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


@pytest.fixture
async def project(db) -> Project:
    return await projects_service.create_project(
        db, ProjectCreate(key="RPX", name="Reporting X")
    )


def _state(states: list[State], category: StateCategory) -> State:
    return next(s for s in states if s.category == category.value)


# --- the timeline helper ---


async def test_item_state_timeline_reconstructs_segments(db, admin, project):
    states = await workflow.list_states(db, project.id)
    inprog = _state(states, StateCategory.IN_PROGRESS)
    done = _state(states, StateCategory.DONE)

    item = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="walk the states"), admin
    )
    await items_service.update_item(db, item.id, ItemUpdate(state_id=inprog.id), admin)
    await items_service.update_item(db, item.id, ItemUpdate(state_id=done.id), admin)

    built = await timeline.build_item_timelines(db, [item.id])
    tl = built[item.id]

    # triage (default) -> in_progress -> done, in order
    assert [seg.category for seg in tl.segments] == [
        StateCategory.TRIAGE,
        StateCategory.IN_PROGRESS,
        StateCategory.DONE,
    ]
    # the two earlier stays are completed (have an exit); the last is still open
    assert tl.segments[0].exited_at is not None
    assert tl.segments[1].exited_at is not None
    assert tl.segments[-1].exited_at is None
    # entering done was recorded exactly once
    assert len(tl.done_entries) == 1
    assert tl.project_id == project.id and tl.kind == "issue"

    # the public helper exposes just the ordered segments
    segments = await timeline.item_state_timeline(db, [item.id])
    assert segments[item.id] == tl.segments


async def test_timeline_collapses_repeats_and_recounts_reentry(db, admin, project):
    states = await workflow.list_states(db, project.id)
    inprog = _state(states, StateCategory.IN_PROGRESS)
    done = _state(states, StateCategory.DONE)

    item = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="reopened"), admin
    )
    # to done, back to in-progress, to done again, then a no-op edit (same state)
    await items_service.update_item(db, item.id, ItemUpdate(state_id=done.id), admin)
    await items_service.update_item(db, item.id, ItemUpdate(state_id=inprog.id), admin)
    await items_service.update_item(db, item.id, ItemUpdate(state_id=done.id), admin)
    await items_service.update_item(db, item.id, ItemUpdate(title="rename only"), admin)

    tl = (await timeline.build_item_timelines(db, [item.id]))[item.id]
    # the title-only edit did not open a new segment
    assert [seg.category for seg in tl.segments] == [
        StateCategory.TRIAGE,
        StateCategory.DONE,
        StateCategory.IN_PROGRESS,
        StateCategory.DONE,
    ]
    # two distinct entries into a done state
    assert len(tl.done_entries) == 2


# --- one report end-to-end ---


async def test_throughput_counts_items_that_entered_done(db, admin, project):
    done = _state(await workflow.list_states(db, project.id), StateCategory.DONE)

    for i in range(3):
        item = await items_service.create_item(
            db, ItemCreate(project_id=project.id, title=f"done {i}"), admin
        )
        await items_service.update_item(db, item.id, ItemUpdate(state_id=done.id), admin)
    # one item never reaches done — must not be counted
    await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="still open"), admin
    )

    rows = await reporting.throughput(
        db, project.id, date.today() - timedelta(days=1), date.today(), ReportInterval.DAY
    )
    assert sum(row.count for row in rows) == 3
    # The 3 completions land in a single bucket; which calendar day depends on the
    # event-timestamp timezone (UTC), which can differ from the local date near
    # midnight — so assert the shape, not that the bucket is local-"today".
    assert max((row.count for row in rows), default=0) == 3
    # scope is the project: an unrelated project sees nothing
    empty = await reporting.throughput(
        db, uuid.uuid4(), date.today() - timedelta(days=1), date.today(), ReportInterval.DAY
    )
    assert all(row.count == 0 for row in empty)
