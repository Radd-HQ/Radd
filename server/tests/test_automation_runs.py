"""Run history (RADD-1266): an applying walk leaves a row in the dry run's
shape; a dry run leaves none; the newest run rides the rule read; old rows are
swept."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from radd.clock import utcnow
from radd.config import settings
from radd.modules.auth.models import User
from radd.modules.automations import engine, runs, service as automations
from radd.modules.automations.models import AutomationRun
from radd.modules.automations.schemas import RuleCreate
from radd.modules.automations.types import SYSTEM_ACTOR_ID, RunSource, RunStatus
from radd.modules.comments import service as comments_service
from radd.modules.events import service as events
from radd.modules.items import service as items_service
from radd.modules.items.enums import ItemEvent, Priority
from radd.modules.items.schemas import ItemCreate, ItemUpdate
from radd.modules.auth.types import InstanceRole

from _factories import make_project, make_user


@pytest.fixture
async def admin(db) -> User:
    return await make_user(db, role=InstanceRole.ADMIN, name="Runs Admin")


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
    project = await make_project(db, "RN", "Runs")
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
    project = await make_project(db, "RN", "Runs")
    rule = await automations.create_rule(
        db, _graph(project.key, {"type": "action.set_priority", "params": {"priority": "high"}}), admin.id
    )
    item = await items_service.create_item(db, ItemCreate(project_id=project.id, title="t"), admin)
    await engine.preview(db, rule, item.id)
    assert await runs.list_runs(db, rule.id) == []


async def test_a_skipped_action_reads_as_nothing_to_do_with_the_reason_kept(db, admin):
    project = await make_project(db, "RN", "Runs")
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
    project = await make_project(db, "RN", "Runs")
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
    # RADD-1450: the engine's own report names the run that failed, at its depth.
    assert failed.automated and failed.automation_rule_id == rule.id and failed.automation_depth == 1


async def test_old_runs_are_swept_and_recent_ones_kept(db, admin, monkeypatch):
    project = await make_project(db, "RN", "Runs")
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


# --- RADD-1450: a skip does not halt the branch; ownerless rules run as the system ---


def _chain(*actions: dict) -> RuleCreate:
    """A manual trigger wired through `actions` in series: trg -> a0 -> a1 -> …"""
    nodes = [{"id": "trg", "kind": "trigger", "type": "trigger.event", "params": {"event": "manual"}}]
    edges = []
    previous = "trg"
    for index, action in enumerate(actions):
        node_id = f"a{index}"
        nodes.append({"id": node_id, "kind": "action", **action})
        edges.append({"source": previous, "port": "out", "target": node_id})
        previous = node_id
    return RuleCreate.model_validate({"name": "chain proof", "nodes": nodes, "edges": edges})


async def test_a_skipped_item_action_still_feeds_the_next_node(db, admin):
    """add_watcher(assignee) on an unassigned item SKIPS; the comment after it
    must still land — a skip is "nothing to do here", not a failure."""
    project = await make_project(db, "RN", "Runs")
    rule = await automations.create_rule(
        db,
        _chain(
            {"type": "action.add_watcher", "params": {"user": "assignee"}},
            {"type": "action.add_comment", "params": {"body": "after the skip", "visibility": "public"}},
        ),
        admin.id,
    )
    item = await items_service.create_item(db, ItemCreate(project_id=project.id, title="unassigned"), admin)

    assert await engine.run_manual(db, rule, item.id, start_node_id="trg")

    bodies = [c.body for c in await comments_service.public_comments_for_item(db, item.id)]
    assert bodies == ["after the skip"]
    run = (await runs.list_runs(db, rule.id))[0]
    assert run.status == RunStatus.APPLIED.value
    assert (run.actions_skipped, run.actions_applied) == (1, 1)
    assert "no assignee" in run.report["would_apply"][0]["detail"]


async def test_a_skipped_set_action_still_feeds_the_next_node(db, admin):
    """A SET-arity skip has no item to drop; before RADD-1450 it emptied the packet."""
    project = await make_project(db, "RN", "Runs")
    rule = await automations.create_rule(
        db,
        _chain(
            {"type": "action.notify_user", "params": {"user": "nobody@example.invalid", "message": "hi"}},
            {"type": "action.set_flag", "params": {"flagged": True}},
        ),
        admin.id,
    )
    item = await items_service.create_item(db, ItemCreate(project_id=project.id, title="t"), admin)

    assert await engine.run_manual(db, rule, item.id, start_node_id="trg")

    assert (await items_service.require_item(db, item.id)).flagged
    run = (await runs.list_runs(db, rule.id))[0]
    assert run.status == RunStatus.APPLIED.value and run.actions_skipped == 1


async def test_a_failed_action_halts_the_branch_and_the_report_names_the_run(db, admin, monkeypatch):
    from radd.modules.automations import builtin_actions

    project = await make_project(db, "RN", "Runs")
    rule = await automations.create_rule(
        db,
        _chain(
            {"type": "action.set_priority", "params": {"priority": "high"}},
            {"type": "action.set_flag", "params": {"flagged": True}},
        ),
        admin.id,
    )
    item = await items_service.create_item(db, ItemCreate(project_id=project.id, title="t"), admin)
    original = builtin_actions.apply_action

    async def broken(ctx, plan):
        if ctx.node.id == "a0":
            raise RuntimeError("provider unavailable")
        return await original(ctx, plan)

    monkeypatch.setattr(builtin_actions, "apply_action", broken)
    head = await _head(db)
    await engine.run_manual(db, rule, item.id, start_node_id="trg")

    assert not (await items_service.require_item(db, item.id)).flagged
    run = (await runs.list_runs(db, rule.id))[0]
    assert run.status == RunStatus.FAILED.value and "provider unavailable" in run.error
    failed = await _last_event(db, "automation.run_failed", head)
    assert failed.automation_rule_id == rule.id and failed.automation_depth == 1


async def test_an_ownerless_rule_runs_as_the_system_actor(db, admin):
    """A row predating the owner column keeps running — as the system actor, and
    the run row says so."""
    project = await make_project(db, "RN", "Runs")
    rule = await automations.create_rule(
        db, _chain({"type": "action.set_priority", "params": {"priority": "high"}}), admin.id
    )
    rule.created_by_id = None
    await db.flush()
    item = await items_service.create_item(db, ItemCreate(project_id=project.id, title="t"), admin)

    assert await engine.run_manual(db, rule, item.id, start_node_id="trg")

    assert (await items_service.require_item(db, item.id)).priority == Priority.HIGH.value
    run = (await runs.list_runs(db, rule.id))[0]
    assert run.status == RunStatus.APPLIED.value and run.actor_id == SYSTEM_ACTOR_ID


async def test_a_deactivated_owner_still_fails_the_run_closed(db, admin):
    project = await make_project(db, "RN", "Runs")
    rule = await automations.create_rule(
        db, _chain({"type": "action.set_priority", "params": {"priority": "high"}}), admin.id
    )
    item = await items_service.create_item(db, ItemCreate(project_id=project.id, title="t"), admin)
    admin.active = False
    await db.flush()

    await engine.run_manual(db, rule, item.id, start_node_id="trg")

    assert (await items_service.require_item(db, item.id)).priority != Priority.HIGH.value
    run = (await runs.list_runs(db, rule.id))[0]
    assert run.status == RunStatus.FAILED.value and "execution account is unavailable" in run.error
