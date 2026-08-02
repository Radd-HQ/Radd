"""Story points (spec 70): SLQ `points`, report measures, bounds, cycle sums.

DB-backed (compose Postgres) — flushed, never committed; the session rolls back
at teardown, so rows never persist. Items are driven through the real items
service so the reports' event-log timelines see genuine payloads.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from radd.config import settings as config
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.cycles import service as cycles_service
from radd.modules.cycles.schemas import CycleCreate
from radd.modules.items import service as items
from radd.modules.items.filters import ItemListFilters
from radd.modules.items.schemas import ItemCreate, ItemUpdate
from radd.modules.reporting import service as reporting
from radd.modules.reporting.types import ReportMeasure
from radd.modules.workflow import service as workflow
from radd.modules.workflow.types import StateCategory
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


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
        email=f"pts-{uuid.uuid4().hex[:8]}@example.com",
        name="Points Tester",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _project_with_states(db):
    project = await projects_service.create_project(
        db,
        ProjectCreate(key=f"PT{uuid.uuid4().hex[:4].upper()}", name="P"),
    )
    states = {s.category: s for s in await workflow.list_states(db, project.id)}
    return project, states


async def _slq(db, actor, project, q):
    rows = await items.list_items(
        db,
        actor=actor,
        filters=ItemListFilters(project_id=project.id),
        q=q,
        limit=50,
        offset=0,
    )
    return [r.title for r in rows]


# --- create/update semantics + bounds ---


async def test_points_roundtrip_and_clear(db, actor):
    project, _ = await _project_with_states(db)
    item = await items.create_item(
        db, ItemCreate(project_id=project.id, title="estimated", estimate_points=2.5), actor
    )
    assert item.estimate_points == 2.5
    # Omitted = unchanged; explicit null clears (model_fields_set idiom).
    kept = await items.update_item(db, item.id, ItemUpdate(title="renamed"), actor)
    assert kept.estimate_points == 2.5
    cleared = await items.update_item(db, item.id, ItemUpdate(estimate_points=None), actor)
    assert cleared.estimate_points is None


def test_points_bounds_validate():
    project_id = uuid.uuid4()
    with pytest.raises(ValidationError):
        ItemCreate(project_id=project_id, title="neg", estimate_points=-1)
    with pytest.raises(ValidationError):
        ItemCreate(project_id=project_id, title="big", estimate_points=1000)
    with pytest.raises(ValidationError):
        ItemUpdate(estimate_points=999.5)


# --- SLQ ---


async def test_slq_points_filters_and_order(db, actor):
    project, _ = await _project_with_states(db)
    for title, points in (("small", 1), ("large", 5), ("unsized", None)):
        await items.create_item(
            db,
            ItemCreate(project_id=project.id, title=title, estimate_points=points),
            actor,
        )

    assert await _slq(db, actor, project, "points > 3") == ["large"]
    assert await _slq(db, actor, project, "points <= 1") == ["small"]
    assert await _slq(db, actor, project, "points IS EMPTY") == ["unsized"]
    assert set(await _slq(db, actor, project, "points IS NOT EMPTY")) == {"small", "large"}
    # Postgres null placement: ASC puts NULLs last, DESC first (same as CF sorts).
    assert await _slq(db, actor, project, "ORDER BY points ASC") == ["small", "large", "unsized"]
    assert (await _slq(db, actor, project, "ORDER BY points DESC"))[-2:] == ["large", "small"]


# --- reports: measure=count vs measure=points ---


async def _seeded_completed_cycle(db, actor):
    """A completed cycle with 2 done items (3 + 1.5 pts) and 1 open (8 pts)."""
    project, states = await _project_with_states(db)
    today = date.today()
    cycle = await cycles_service.create_cycle(
        db,
        CycleCreate(
            name=f"Sprint {uuid.uuid4().hex[:6]}",
            start_date=today - timedelta(days=6),
            end_date=today,
        ),
        today=today,
        actor_id=actor.id,
    )
    done = states[StateCategory.DONE.value]
    for title, points, finish in (("a", 3, True), ("b", 1.5, True), ("c", 8, False)):
        item = await items.create_item(
            db,
            ItemCreate(
                project_id=project.id, title=title, estimate_points=points, cycle_id=cycle.id
            ),
            actor,
        )
        if finish:
            await items.update_item(db, item.id, ItemUpdate(state_id=done.id), actor)
    # Stamp the close so the derived status is COMPLETED regardless of dates.
    raw = await cycles_service.get_cycle(db, cycle.id)
    raw.completed_at = datetime.now(UTC).replace(tzinfo=None)
    await db.flush()
    return project, cycle


async def test_velocity_measures(db, actor):
    _, cycle = await _seeded_completed_cycle(db, actor)
    by_count = await reporting.velocity(db, last=5)
    row = next(r for r in by_count if r.cycle.id == cycle.id)
    assert row.completed == 2
    by_points = await reporting.velocity(db, last=5, measure=ReportMeasure.POINTS)
    row = next(r for r in by_points if r.cycle.id == cycle.id)
    assert row.completed == 4.5  # 3 + 1.5; the open 8-pointer doesn't count


async def test_burnup_measures(db, actor):
    _, cycle = await _seeded_completed_cycle(db, actor)
    by_count = await reporting.burnup(db, cycle.id)
    assert by_count.series[-1].scope == 3
    assert by_count.series[-1].completed == 2
    by_points = await reporting.burnup(db, cycle.id, measure=ReportMeasure.POINTS)
    assert by_points.series[-1].scope == 12.5  # 3 + 1.5 + 8
    assert by_points.series[-1].completed == 4.5


# --- cycle stats sums ---


async def test_cycle_points_totals_and_filters(db, actor):
    project, cycle = await _seeded_completed_cycle(db, actor)
    total, done = await items.cycle_points_totals(db, cycle.id)
    assert (total, done) == (12.5, 4.5)
    # The same filter seam as cycle_state_category_counts.
    total, done = await items.cycle_points_totals(db, cycle.id, project_id=project.id)
    assert (total, done) == (12.5, 4.5)
    total, done = await items.cycle_points_totals(db, cycle.id, project_id=uuid.uuid4())
    assert (total, done) == (0.0, 0.0)
    total, done = await items.cycle_points_totals(db, cycle.id, assignee_id=actor.id)
    assert (total, done) == (0.0, 0.0)  # nothing assigned to the actor
