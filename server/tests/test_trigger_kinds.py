"""RADD-1323: trigger KINDS are a registry, and a manual run can start from a page.

A plugin's trigger kind is registered here directly into the kernel registry —
the same thing `RaddPlugin.trigger_kinds` does at load — and fired the only way
a plugin can: by emitting an event of the kind's key. Nothing in `automations`
knows the kind exists.
"""

import uuid

import pytest
from sqlalchemy import select

from radd.kernel import TriggerKindSpec
from radd.kernel.registry import registries
from radd.modules.auth.models import User
from radd.modules.automations import engine, service as automations
from radd.modules.automations.schemas import RuleCreate
from radd.modules.events import service as events
from radd.modules.events.models import Event
from radd.modules.items.models import WorkItem
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.auth.types import InstanceRole

from _factories import make_user

KIND = "acme.hook_received"


@pytest.fixture
async def admin(db) -> User:
    return await make_user(db, role=InstanceRole.ADMIN, name="Kind Admin")


@pytest.fixture
def hook_kind():
    """A plugin's "a webhook arrived on endpoint X" kind."""
    spec = TriggerKindSpec(
        key=KIND,
        label="Webhook received",
        group="Acme",
        params_schema={"type": "object", "required": ["endpoint"], "properties": {"endpoint": {"type": "string"}}},
        has_event=True,
        matches=lambda params, payload: params.get("endpoint") == payload.get("endpoint"),
    )
    registries.trigger_kinds[KIND] = spec
    yield spec
    registries.trigger_kinds.pop(KIND, None)


async def _emit(db, endpoint: str) -> Event:
    await events.emit(db, event_type=KIND, entity_type="acme_hook", entity_id=uuid.uuid4(), payload={"endpoint": endpoint})
    await db.flush()
    return (await db.execute(select(Event).where(Event.event_type == KIND).order_by(Event.id.desc()).limit(1))).scalar_one()


async def test_a_plugins_trigger_kind_fires_the_automations_configured_for_it(db, admin, hook_kind):
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"TK{uuid.uuid4().hex[:4].upper()}", name="Kinds")
    )
    title = f"from the hook {uuid.uuid4().hex[:6]}"
    await automations.create_rule(db, RuleCreate.model_validate({
        "name": "on hook a",
        "nodes": [
            {"id": "trg", "kind": "trigger", "type": "trigger.event", "params": {"event": KIND, "endpoint": "a"}},
            {"id": "act", "kind": "action", "type": "action.create_item",
             "params": {"project": project.key, "title": title}},
        ],
        "edges": [{"source": "trg", "port": "out", "target": "act"}],
    }), admin.id)

    async def made() -> int:
        rows = await db.execute(select(WorkItem).where(WorkItem.project_id == project.id, WorkItem.title == title))
        return len(list(rows.scalars()))

    # A firing for ANOTHER endpoint does not match this automation…
    await engine.apply_event(db, await _emit(db, "b"))
    assert await made() == 0
    # …one for its own does.
    await engine.apply_event(db, await _emit(db, "a"))
    assert await made() == 1


async def test_the_catalog_serves_every_kind_including_a_plugins(db, admin, hook_kind):
    import importlib

    router_module = importlib.import_module("radd.modules.automations.router")
    catalog = await router_module.get_catalog(db, admin)
    kinds = {kind.key: kind for kind in catalog.trigger_kinds}
    assert {"manual", "schedule", "validate", KIND} <= set(kinds)
    assert kinds["schedule"].has_event is False and kinds[KIND].has_event is True
    assert "page" in kinds["manual"].seeds


async def test_a_manual_run_can_start_from_a_page(db, admin):
    from radd.modules.comments.models import Comment
    from radd.modules.pages import service as pages, spaces
    from radd.modules.pages.schemas import PageCreate, PageSpaceCreate

    slug = f"k{uuid.uuid4().hex[:6]}"
    space = await spaces.create_space(db, PageSpaceCreate(name=f"Space {slug}", slug=slug), admin.id)
    page = await pages.create_page(db, PageCreate(space_id=space.id, title="Runbook", body="x"), admin.id)
    rule = await automations.create_rule(db, RuleCreate.model_validate({
        "name": "stamp the page",
        "nodes": [
            {"id": "trg", "kind": "trigger", "type": "trigger.event", "params": {"event": "manual"}},
            {"id": "act", "kind": "action", "type": "page.comment", "params": {"body": "Reviewed."}},
        ],
        "edges": [{"source": "trg", "port": "out", "target": "act"}],
    }), admin.id)

    ran = await engine.run_manual(db, rule, page.id, start_node_id="trg", subject="page")
    await db.flush()
    comments = list((await db.execute(select(Comment).where(Comment.entity_id == page.id))).scalars())
    assert ran and [c.body for c in comments] == ["Reviewed."]
