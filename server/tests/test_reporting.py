"""Reporting (spec 16): the item state history + the reports that aggregate it.

Everything runs against live Postgres inside a single rolled-back transaction, so
nothing persists. Items are driven through the real `items.service`, which writes
an `item_transitions` row with each state or cycle change (RADD-1537) — what the
reports read. The history is ordered by row id, not the clock, so several changes
inside one instant still come back in the order they were made.
"""

import importlib.util
import json
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import delete, select, text

from radd.modules.cycles import service as cycles_service
from radd.modules.cycles.schemas import CycleCreate
from radd.modules.items.models import ItemTransition

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


async def test_imported_completion_reports_in_its_historical_bucket(db, admin, project):
    """An import (project.manage) restates `created_at`/`updated_at`; the EVENTS
    must carry those times too, or every report files the whole import under today."""
    done = _state(await workflow.list_states(db, project.id), StateCategory.DONE)
    raised = datetime(2024, 5, 6, 9, 30)
    closed = datetime(2024, 5, 8, 16, 0)

    item = await items_service.create_item(
        db,
        ItemCreate(project_id=project.id, title="imported", created_at=raised),
        admin,
    )
    await items_service.update_item(
        db, item.id, ItemUpdate(state_id=done.id, updated_at=closed), admin
    )

    tl = (await timeline.build_item_timelines(db, [item.id]))[item.id]
    assert [entry.at.date() for entry in tl.done_entries] == [closed.date()]

    rows = await reporting.throughput(
        db, project.id, raised.date(), closed.date(), ReportInterval.DAY
    )
    counted = {row.bucket: row.count for row in rows if row.count}
    assert counted == {closed.date().isoformat(): 1}
    # ...and nothing lands in the present, which is where it used to go
    today = await reporting.throughput(
        db, project.id, date.today() - timedelta(days=1), date.today(), ReportInterval.DAY
    )
    assert all(row.count == 0 for row in today)


# --- the reports that need more than a count (RADD-1537) ---


async def _walked(db, admin, project) -> uuid.UUID:
    """One item: raised 6 May 09:30, started 7 May 09:30, finished 8 May 16:00."""
    states = await workflow.list_states(db, project.id)
    item = await items_service.create_item(
        db,
        ItemCreate(project_id=project.id, title="walked", created_at=datetime(2024, 5, 6, 9, 30)),
        admin,
    )
    for category, at in (
        (StateCategory.IN_PROGRESS, datetime(2024, 5, 7, 9, 30)),
        (StateCategory.DONE, datetime(2024, 5, 8, 16, 0)),
    ):
        await items_service.update_item(
            db, item.id, ItemUpdate(state_id=_state(states, category).id, updated_at=at), admin
        )
    return item.id


async def test_cumulative_flow_is_the_distribution_at_each_days_end(db, admin, project):
    await _walked(db, admin, project)
    # A second item raised on the 7th and never moved: it joins the chart then.
    await items_service.create_item(
        db,
        ItemCreate(project_id=project.id, title="waiting", created_at=datetime(2024, 5, 7, 12, 0)),
        admin,
    )
    rows = await reporting.cumulative_flow(
        db, project.id, date(2024, 5, 5), date(2024, 5, 9), ReportInterval.DAY
    )
    held = {row.bucket: {k: v for k, v in row.counts.items() if v} for row in rows}
    assert held == {
        "2024-05-05": {},
        "2024-05-06": {"triage": 1},
        "2024-05-07": {"in_progress": 1, "triage": 1},
        "2024-05-08": {"done": 1, "triage": 1},
        "2024-05-09": {"done": 1, "triage": 1},
    }
    # A window that opens AFTER the history starts from the balance carried in.
    late = await reporting.cumulative_flow(
        db, project.id, date(2024, 5, 9), date(2024, 5, 9), ReportInterval.DAY
    )
    assert {k: v for k, v in late[0].counts.items() if v} == {"done": 1, "triage": 1}
    # Every category is reported, zero or not: the chart stacks all of them.
    assert set(late[0].counts) == {category.value for category in StateCategory}


async def test_time_in_state_measures_completed_stays(db, admin, project):
    await _walked(db, admin, project)
    rows = {row.category: row for row in await reporting.time_in_state(db, project.id)}
    # 24 h in triage, 30.5 h in progress; the open stay in done is not a sample.
    assert rows[StateCategory.TRIAGE].avg_hours == 24.0
    assert rows[StateCategory.IN_PROGRESS].median_hours == 30.5
    assert StateCategory.DONE not in rows
    assert all(row.sample == 1 for row in rows.values())


async def test_a_throughput_report_reads_only_its_window(db, admin, project):
    """The plan, not the result: the window is an index range on
    `(project_id, at)`, so a 30-day report never visits the years before it."""
    await _walked(db, admin, project)
    statement = reporting.throughput_statement(project.id, date(2024, 5, 1), date(2024, 5, 31))
    compiled = statement.compile(db.bind, compile_kwargs={"literal_binds": True})
    await db.execute(text("SET LOCAL enable_seqscan = off"))
    plan = (await db.execute(text(f"EXPLAIN (FORMAT JSON) {compiled}"))).scalar_one()
    plan = json.dumps(plan)
    assert "ix_item_transitions_project_at" in plan
    # Both ends of the window are in the index condition, not a filter after it.
    condition = plan[plan.index("Index Cond") :].split('"', 4)[2]
    assert ">=" in condition and "<" in condition.replace(">=", "")


async def test_the_migrations_fold_agrees_with_what_the_writer_recorded(db, admin, project):
    """Two implementations of one rule: `transitions.record` writes history as it
    happens, the `d1537transitions` backfill derives it from the ledger for
    everything that happened before. Run the backfill over the events this test
    just emitted and it must reproduce the rows the writer made."""
    states = await workflow.list_states(db, project.id)
    done = _state(states, StateCategory.DONE)
    inprog = _state(states, StateCategory.IN_PROGRESS)
    cycle = await cycles_service.create_cycle(
        db, CycleCreate(name="fold", start_date=date(2024, 5, 6), end_date=date(2024, 5, 19)),
        date.today(),
    )
    first = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="reopened"), admin
    )
    for patch in (
        ItemUpdate(state_id=done.id),
        ItemUpdate(title="a rename is not history"),
        ItemUpdate(cycle_id=cycle.id),
        ItemUpdate(state_id=inprog.id),
        ItemUpdate(state_id=done.id, cycle_id=None),
    ):
        await items_service.update_item(db, first.id, patch, admin)
    second = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="born in a cycle", cycle_id=cycle.id), admin
    )
    await items_service.update_item(db, second.id, ItemUpdate(state_id=inprog.id), admin)

    async def history():
        rows = await db.execute(
            select(
                ItemTransition.item_id, ItemTransition.state_id, ItemTransition.category,
                ItemTransition.cycle_id, ItemTransition.state_changed, ItemTransition.entered_done,
                ItemTransition.from_state_id, ItemTransition.from_category,
                ItemTransition.from_cycle_id,
            )
            .where(ItemTransition.project_id == project.id)
            .order_by(ItemTransition.item_id, ItemTransition.id)
        )
        return [tuple(row) for row in rows]

    written = await history()
    assert len(written) == 7  # 5 for the first item (the rename wrote nothing), 2 for the second

    (path,) = (Path(__file__).parents[1] / "migrations/versions").glob("d1537transitions*.py")
    spec = importlib.util.spec_from_file_location("d1537transitions", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    await db.execute(delete(ItemTransition))
    for statement in (migration._FOLD, migration._UNSEEN, migration._CATCH_UP):
        await db.execute(text(statement))
    assert await history() == written
