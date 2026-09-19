"""Run history (RADD-1266): an applying walk leaves a row in the dry run's
shape; a dry run leaves none; the newest run rides the rule read; old rows are
swept."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.clock import utcnow
from radd.config import settings
from radd.modules.auth.models import User
from radd.modules.automations import engine, runs, service as automations
from radd.modules.automations.models import AutomationRun
from radd.modules.automations.schemas import RuleCreate
from radd.modules.automations.types import RunSource, RunStatus
from radd.modules.events import service as events
from radd.modules.items import service as items_service
from radd.modules.items.enums import ItemEvent, Priority
from radd.modules.items.schemas import ItemCreate, ItemUpdate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate


@pytest.fixture
async def db():
    engine_ = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine_, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine_.dispose()


@pytest.fixture
async def admin(db) -> User:
    user = User(email=f"runs-{uuid.uuid4().hex[:8]}@example.com", name="Runs Admin", instance_role="admin")
    db.add(user)
    await db.flush()
    return user


async def _project(db):
    return await projects_service.create_project(
        db, ProjectCreate(key=f"RN{uuid.uuid4().hex[:4].upper()}", name="Runs")
    )


def _graph(project_key: str, action: dict) -> RuleCreate:
    return RuleCreate.model_validate(
        {
            "name": "runs proof",
            "nodes": [
                {"id": "trg", "kind": "trigger", "type": "trigger.event", "params": {"event": ItemEvent.UPDATED.value}},
                {"id": "flt", "kind": "filter", "type": "filter.slq", "params": {"slq": f"project = {project_key}"}},
                {"id": "act", "kind": "action", **action},
            ],
            "edges": [
                {"source": "trg", "port": "out", "target": "flt"},
                {"source": "flt", "port": "matched", "target": "act"},
            ],
        }
    )


async def _last_event(db, event_type: str, since: int):
    rows = await events.read_after(db, since, 200)
    matching = [e for e in rows if e.event_type == event_type]
    assert matching, f"no {event_type} after {since}"
    return matching[-1]


async def _head(db) -> int:
    return (await db.execute(select(events.Event.id).order_by(events.Event.id.desc()).limit(1))).scalar() or 0


async def test_an_applying_run_is_recorded_in_the_dry_run_shape(db, admin):
    project = await _project(db)
    rule = await automations.create_rule(
        db, _graph(project.key, {"type": "action.set_priority", "params": {"priority": "high"}}), admin.id
    )
    item = await items_service.create_item(db, ItemCreate(project_id=project.id, title="t"), admin)
    head = await _head(db)
    await items_service.update_item(db, item.id, ItemUpdate(title="renamed"), actor=admin)
    event = await _last_event(db, ItemEvent.UPDATED.value, head)

    await engine.apply_event(db, event)

    rows = await runs.list_runs(db, rule.id)
    assert len(rows) == 1
    run = rows[0]
    assert run.status == RunStatus.APPLIED.value
    assert run.source == RunSource.EVENT.value
    assert run.event_id == event.id and run.event_type == ItemEvent.UPDATED.value
    assert run.trigger_node_id == "trg"
    assert run.item_keys == [item.key]
    assert run.actions_applied == 1 and run.actions_skipped == 0
    # The report is the dry run's own shape, per node.
    by_id = {node["node_id"]: node for node in run.report["nodes"]}
    assert by_id["flt"]["ran"] and by_id["act"]["ran"]
    assert run.report["would_apply"][0]["node_id"] == "act"
    assert (await items_service.require_item(db, item.id)).priority == Priority.HIGH.value

    # The rule read carries the newest run.
    read = (await automations.rule_reads(db, [rule]))[0]
    assert read.last_run_status == RunStatus.APPLIED.value and read.last_run_at is not None


async def test_a_dry_run_records_nothing(db, admin):
    project = await _project(db)
    rule = await automations.create_rule(
        db, _graph(project.key, {"type": "action.set_priority", "params": {"priority": "high"}}), admin.id
    )
    item = await items_service.create_item(db, ItemCreate(project_id=project.id, title="t"), admin)
    await engine.preview(db, rule, item.id)
    assert await runs.list_runs(db, rule.id) == []


async def test_a_skipped_action_reads_as_nothing_to_do_with_the_reason_kept(db, admin):
    project = await _project(db)
    rule = await automations.create_rule(
        db, _graph(project.key, {"type": "action.set_assignee", "params": {"assignee": "nobody@example.invalid"}}), admin.id
    )
    item = await items_service.create_item(db, ItemCreate(project_id=project.id, title="t"), admin)
    head = await _head(db)
    await items_service.update_item(db, item.id, ItemUpdate(title="renamed"), actor=admin)
    await engine.apply_event(db, await _last_event(db, ItemEvent.UPDATED.value, head))

    run = (await runs.list_runs(db, rule.id))[0]
    assert run.status == RunStatus.NOTHING_TO_DO.value
    assert run.actions_skipped == 1
    assert "no user" in run.report["would_apply"][0]["detail"]


async def test_a_walk_that_raises_is_recorded_as_failed_and_emits(db, admin, monkeypatch):
    project = await _project(db)
    rule = await automations.create_rule(
        db, _graph(project.key, {"type": "action.set_priority", "params": {"priority": "high"}}), admin.id
    )
    item = await items_service.create_item(db, ItemCreate(project_id=project.id, title="t"), admin)
    head = await _head(db)
    await items_service.update_item(db, item.id, ItemUpdate(title="renamed"), actor=admin)
    event = await _last_event(db, ItemEvent.UPDATED.value, head)

    async def boom(*_args, **_kwargs):
        raise RuntimeError("the walk exploded")

    from radd.modules.automations import executor

    monkeypatch.setattr(executor, "walk", boom)
    await engine.apply_event(db, event)  # does not raise: one bad automation must not stall the consumer

    run = (await runs.list_runs(db, rule.id))[0]
    assert run.status == RunStatus.FAILED.value
    assert "the walk exploded" in run.error and run.report == {}
    failed = await _last_event(db, "automation.run_failed", event.id)
    assert failed.payload["name"] == "runs proof" and "exploded" in failed.payload["error"]


async def test_old_runs_are_swept_and_recent_ones_kept(db, admin, monkeypatch):
    project = await _project(db)
    rule = await automations.create_rule(
        db, _graph(project.key, {"type": "action.set_priority", "params": {"priority": "high"}}), admin.id
    )
    now = utcnow()
    for age_days in (1, 40):
        db.add(
            AutomationRun(
                automation_id=rule.id, trigger_node_id="trg", source="event", event_type="item.updated",
                started_at=now - timedelta(days=age_days), finished_at=now - timedelta(days=age_days),
                status="applied", item_keys=[], report={},
            )
        )
    await db.flush()
    monkeypatch.setattr(settings, "automation_run_retention_days", 30)
    assert await runs.sweep(db, now=now) == 1
    assert len(await runs.list_runs(db, rule.id)) == 1
    monkeypatch.setattr(settings, "automation_run_retention_days", 0)
    assert await runs.sweep(db, now=now) == 0
