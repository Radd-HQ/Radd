"""RADD-1315: automation chaining is opt-in per trigger, never self-triggering,
and capped in depth.

The engine is driven the way the consumer drives it — every new event after a
cursor, fed to `apply_event`, until the stream is quiet — so a chain that did
not terminate would show up here as a loop that hits the iteration guard.
Actions run as each automation's AUTHOR (a real person), which is the "works
with act_as" half: causation is the event's marker, not who acted.
"""


import pytest
from sqlalchemy import select

from radd.config import settings
from radd.exceptions import ConflictError
from radd.modules.automations import engine, service as automations
from radd.modules.automations.schemas import RuleCreate
from radd.modules.events.models import Event
from radd.modules.items import service as items_service
from radd.modules.items.enums import ItemEvent
from radd.modules.items.schemas import ItemCreate, ItemUpdate

from _factories import make_project


@pytest.fixture
async def project(db):
    return await make_project(db, "CH")


def _rule(name: str, project_key: str, action: dict, *, include_automated: bool = False) -> RuleCreate:
    trigger_params: dict = {"event": ItemEvent.UPDATED.value}
    if include_automated:
        trigger_params["include_automated"] = True
    return RuleCreate.model_validate({
        "name": name,
        "nodes": [
            {"id": "trg", "kind": "trigger", "type": "trigger.event", "params": trigger_params},
            {"id": "flt", "kind": "filter", "type": "filter.slq", "params": {"slq": f"project = {project_key}"}},
            {"id": "act", "kind": "action", **action},
        ],
        "edges": [
            {"source": "trg", "port": "out", "target": "flt"},
            {"source": "flt", "port": "matched", "target": "act"},
        ],
    })


async def _head(db) -> int:
    return (await db.execute(select(Event.id).order_by(Event.id.desc()).limit(1))).scalar() or 0


async def _drain(db, since: int, *, max_rounds: int = 20) -> list[Event]:
    """Feed every event after `since` to the engine, then the events THAT made,
    until nothing new appears. Returns everything emitted."""
    seen: list[Event] = []
    cursor = since
    for _ in range(max_rounds):
        batch = list((await db.execute(select(Event).where(Event.id > cursor).order_by(Event.id))).scalars())
        if not batch:
            return seen
        cursor = batch[-1].id
        seen.extend(batch)
        for event in batch:
            await engine.apply_event(db, event)
            await db.flush()
    raise AssertionError("the chain never went quiet")


async def _labels(db, item_id, admin) -> set[str]:
    read = await items_service.get_item(db, item_id, admin)
    return {getattr(label, "name", label) for label in (read.labels or [])}


async def test_an_opted_in_trigger_runs_on_another_automations_change(db, admin, project):
    # A: a person's edit → priority high. B (opted in): any change → label.
    await automations.create_rule(
        db, _rule("A", project.key, {"type": "action.set_priority", "params": {"priority": "high"}}), admin.id
    )
    await automations.create_rule(
        db, _rule("B", project.key, {"type": "action.add_label", "params": {"label": "chained"}}, include_automated=True),
        admin.id,
    )
    item = await items_service.create_item(db, ItemCreate(project_id=project.id, title="t"), admin)
    head = await _head(db)
    await items_service.update_item(db, item.id, ItemUpdate(title="edited"), actor=admin)
    emitted = await _drain(db, head)

    assert "chained" in await _labels(db, item.id, admin)
    automated = [e for e in emitted if e.automated]
    # Every automated write says which automation made it, and how deep.
    assert automated and all(e.automation_rule_id is not None and e.automation_depth >= 1 for e in automated)
    assert max(e.automation_depth for e in automated) <= settings.automation_max_chain_depth


async def test_an_opted_out_trigger_ignores_other_automations(db, admin, project):
    await automations.create_rule(
        db, _rule("A", project.key, {"type": "action.set_priority", "params": {"priority": "high"}}), admin.id
    )
    await automations.create_rule(
        db, _rule("B", project.key, {"type": "action.add_label", "params": {"label": "chained"}}), admin.id
    )
    item = await items_service.create_item(db, ItemCreate(project_id=project.id, title="t"), admin)
    head = await _head(db)
    await items_service.update_item(db, item.id, ItemUpdate(title="edited"), actor=admin)
    await _drain(db, head)
    # B ran once, on the PERSON's edit — its label is there — and A's change
    # did not run it again (which would be invisible here), so check the runs.
    from radd.modules.automations import runs

    rules = {r.name: r for r in await automations.list_rules(db) if r.name in ("A", "B")}
    b_runs = [r for r in await runs.list_runs(db, rules["B"].id) if r.status == "applied"]
    assert len(b_runs) == 1


async def test_an_automation_never_runs_on_its_own_change_even_opted_in(db, admin, project):
    rule = await automations.create_rule(
        db, _rule("Self", project.key, {"type": "action.add_label", "params": {"label": "self"}}, include_automated=True),
        admin.id,
    )
    item = await items_service.create_item(db, ItemCreate(project_id=project.id, title="t"), admin)
    head = await _head(db)
    await items_service.update_item(db, item.id, ItemUpdate(title="edited"), actor=admin)
    await _drain(db, head)
    from radd.modules.automations import runs

    applied = [r for r in await runs.list_runs(db, rule.id) if r.status == "applied"]
    assert len(applied) == 1


async def test_two_opted_in_automations_that_feed_each_other_stop_at_the_depth_cap(db, admin, project):
    # Ping-pong: each flips the priority the other reacts to.
    await automations.create_rule(
        db, _rule("Ping", project.key, {"type": "action.set_priority", "params": {"priority": "high"}}, include_automated=True),
        admin.id,
    )
    await automations.create_rule(
        db, _rule("Pong", project.key, {"type": "action.set_priority", "params": {"priority": "low"}}, include_automated=True),
        admin.id,
    )
    item = await items_service.create_item(db, ItemCreate(project_id=project.id, title="t"), admin)
    head = await _head(db)
    await items_service.update_item(db, item.id, ItemUpdate(title="edited"), actor=admin)
    emitted = await _drain(db, head)  # raises if it never goes quiet
    depths = [e.automation_depth for e in emitted if e.automated]
    assert depths and max(depths) == settings.automation_max_chain_depth


async def test_only_an_event_trigger_may_include_other_automations(db, admin):
    bad = RuleCreate.model_validate({
        "name": "manual include",
        "nodes": [
            {"id": "trg", "kind": "trigger", "type": "trigger.event", "params": {"event": "manual", "include_automated": True}},
            {"id": "act", "kind": "action", "type": "action.add_label", "params": {"label": "x"}},
        ],
        "edges": [{"source": "trg", "port": "out", "target": "act"}],
    })
    with pytest.raises(ConflictError):
        await automations.create_rule(db, bad, admin.id)
