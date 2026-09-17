"""RADD-1201: grouping/urgency must happen before LIMIT, with real DB scopes."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.projects import service as projects
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.workflow import service as workflow
from radd.modules.items.models import WorkItem
from radd.modules.items.schemas import ItemCreate
from radd.modules.items import service as items
from radd.modules.items.grouped import GroupPageRequest, grouped_items
from radd.modules.slas import service as slas
from radd.modules.slas.schemas import PolicyCreate
from radd.modules.slas.queue import queue_items


@pytest.fixture
async def setup():
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        actor = User(
            email=f"groups-{uuid.uuid4()}@example.com",
            name="Grouping",
            instance_role=InstanceRole.ADMIN.value,
        )
        db.add(actor)
        await db.flush()
        project = await projects.create_project(
            db, ProjectCreate(key=f"GR{uuid.uuid4().hex[:5].upper()}", name="Groups")
        )
        yield db, actor, project
        await db.rollback()
    await engine.dispose()


async def test_rare_state_beyond_global_page_and_independent_group_load(setup):
    db, actor, project = setup
    states = await workflow.list_states(db, project.id)
    seed = await items.create_item(db, ItemCreate(project_id=project.id, title="seed"), actor=actor)
    model = await db.get(WorkItem, seed.id)
    for n in range(2, 205):
        db.add(
            WorkItem(
                project_id=project.id,
                number=n,
                title=f"row {n}",
                kind="issue",
                state_id=states[0].id if n < 204 else states[1].id,
                priority="normal",
                rank=n,
            )
        )
    model.rank = 1
    await db.flush()
    request = GroupPageRequest(
        project_id=project.id, axis="state", q="ORDER BY number ASC", item_limit=5
    )
    first = await grouped_items(db, actor, request)
    assert first.total_groups == 2
    assert sum(first.column_totals.values()) == 204
    assert any(i.number == 204 for c in first.cells for i in c.items)
    assert sorted(len(c.items) for c in first.cells) == [1, 5]
    next_page = await grouped_items(db, actor, request.model_copy(update={"item_offset": 5}))
    assert [i.number for c in next_page.cells for i in c.items] == [6, 7, 8, 9, 10]
    hidden = await grouped_items(
        db, actor, request.model_copy(update={"hidden_columns": [str(states[0].id)]})
    )
    assert sum(hidden.column_totals.values()) == 1


async def test_queue_live_deadline_beats_global_rank_and_explicit_order_wins(setup):
    db, actor, project = setup
    normal = await items.create_item(
        db, ItemCreate(project_id=project.id, title="No policy", priority="normal"), actor=actor
    )
    urgent = await items.create_item(
        db, ItemCreate(project_id=project.id, title="Overdue", priority="high"), actor=actor
    )
    nr, ur = await db.get(WorkItem, normal.id), await db.get(WorkItem, urgent.id)
    for number in range(3, 205):
        db.add(
            WorkItem(
                project_id=project.id,
                number=number,
                title=f"normal {number}",
                kind="issue",
                state_id=nr.state_id,
                priority="normal",
                rank=number,
            )
        )
    nr.rank, ur.rank = 1, 9999
    nr.created_at -= timedelta(days=1)
    ur.created_at -= timedelta(days=2)
    await slas.create_policy(
        db,
        PolicyCreate(
            project_id=project.id, name="High response", response_minutes=1, priorities=["high"]
        ),
        actor.id,
    )
    await db.flush()
    result = await queue_items(db, actor, project_id=project.id, q="", limit=1, offset=0)
    assert [i.id for i in result] == [urgent.id]
    second = await queue_items(db, actor, project_id=project.id, q="", limit=1, offset=1)
    assert [i.id for i in second] == [normal.id]
    explicit = await queue_items(
        db, actor, project_id=project.id, q="ORDER BY number ASC", limit=1, offset=0
    )
    assert [i.id for i in explicit] == [normal.id]


@pytest.mark.parametrize("axis", ["state", "priority", "assignee", "epic"])
async def test_group_slices_preserve_order_and_totals_with_lanes(setup, axis):
    db, actor, project = setup
    for n in range(9):
        await items.create_item(
            db,
            ItemCreate(project_id=project.id, title=f"slice {n}",
                       priority="high" if n % 2 else "normal"),
            actor=actor,
        )
    request = GroupPageRequest(project_id=project.id, axis=axis, lane="priority",
                               q="ORDER BY number DESC", item_limit=2)
    full = await grouped_items(db, actor, request.model_copy(update={"item_limit": 50}))
    expected = {(c.column, c.lane): [i.id for i in c.items] for c in full.cells}
    seen = {key: [] for key in expected}
    for offset in range(0, 10, 2):
        page = await grouped_items(db, actor, request.model_copy(update={"item_offset": offset}))
        assert page.column_totals == full.column_totals
        assert page.lane_totals == full.lane_totals
        assert [(c.column, c.lane) for c in page.cells] == list(expected)
        for cell in page.cells:
            seen[cell.column, cell.lane].extend(i.id for i in cell.items)
    assert seen == expected
