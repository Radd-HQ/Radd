"""Review probes: assertions document the observed regressions at bfdbdb5.

These are evidence, not passing acceptance tests for the desired behavior.
All database changes roll back in the repository's isolated test database.
"""
import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.auth.models import User
from radd.modules.automations import engine, service as automations, validation
from radd.modules.automations.schemas import RuleCreate
from radd.modules.events import service as events
from radd.modules.events.models import Event
from radd.modules.items import service as items
from radd.modules.items.schemas import ItemCreate
from radd.modules.projects import service as projects
from radd.modules.projects.schemas import ProjectCreate


@pytest.fixture
async def world():
    dbengine = create_async_engine(settings.database_url)
    async with async_sessionmaker(dbengine, expire_on_commit=False)() as db:
        admin = User(email=f"review-{uuid.uuid4().hex}@example.com", name="Reviewer", instance_role="admin")
        db.add(admin)
        await db.flush()
        project = await projects.create_project(db, ProjectCreate(key=f"RV{uuid.uuid4().hex[:5].upper()}", name="Review"))
        yield db, admin, project
        await db.rollback()
    await dbengine.dispose()


async def test_receivers_share_an_issue_across_projects(world):
    from radd.modules.alertmanager import service
    from radd.modules.alertmanager.schemas import ReceiverCreate
    db, admin, project = world
    other = await projects.create_project(db, ProjectCreate(key=f"RX{uuid.uuid4().hex[:5].upper()}", name="Other"))
    receivers = [await service.create_receiver(db, ReceiverCreate(name=uuid.uuid4().hex, token=uuid.uuid4().hex, project_id=p.id)) for p in (project, other)]
    fingerprint = uuid.uuid4().hex
    payload = {"alerts": [{"status": "firing", "fingerprint": fingerprint, "labels": {"alertname": "DiskFull"}}]}
    assert (await service.process(db, receivers[0], payload))["created"] == 1
    assert (await service.process(db, receivers[1], payload))["created"] == 0
    event = await db.scalar(select(Event).where(Event.event_type == "alertmanager.alert.repeated").order_by(Event.id.desc()).limit(1))
    target = await items.require_item(db, uuid.UUID(event.payload["item"]["id"]))
    assert target.project_id == project.id != receivers[1].project_id


async def test_auto_watch_loses_automation_cause(world):
    from radd.modules.notify import consumer
    db, admin, project = world
    cause = events.AutomationCause(rule_id=uuid.uuid4(), depth=settings.automation_max_chain_depth)
    with events.automated(cause=cause):
        item = await items.create_item(db, ItemCreate(project_id=project.id, title="Automated", reporter_id=admin.id), admin)
    original = await db.scalar(select(Event).where(Event.event_type == "item.created", Event.entity_id == str(item.id)).order_by(Event.id.desc()).limit(1))
    assert original.automated and original.automation_depth == cause.depth
    await consumer._handle(db, original, watch_only=False)
    watched = await db.scalar(select(Event).where(Event.event_type == "item.watched", Event.entity_id == str(item.id)).order_by(Event.id.desc()).limit(1))
    assert watched is not None
    assert not watched.automated and watched.automation_depth == 0 and watched.automation_rule_id is None
    assert engine.should_process(watched)


async def test_verdict_item_tokens_can_describe_a_different_private_item(world):
    from radd.modules.automations import intake
    from radd.exceptions import NotFoundError
    from radd.modules.auth.models import Role, GlobalRoleGrant
    db, admin, project = world
    other = await projects.create_project(db, ProjectCreate(key=f"RS{uuid.uuid4().hex[:5].upper()}", name="Private"))
    with intake.suppressed():
        secret = await items.create_item(db, ItemCreate(project_id=other.id, title="Confidential acquisition"), admin)
        draft = await items.create_item(db, ItemCreate(project_id=project.id, title="Public request"), admin)
    await automations.create_rule(db, RuleCreate.model_validate({
        "name": "Draft token leak", "nodes": [
            {"id": "t", "kind": "trigger", "type": "trigger.event", "params": {"event": "validate", "targets": [{"kind": "project", "id": str(project.id)}]}},
            {"id": "s", "kind": "source", "type": "search.slq", "params": {"slq": f"project = {other.key}", "mode": "replace"}},
            {"id": "v", "kind": "action", "type": "verdict.warn", "params": {"message": "Draft: {{item.title}}"}},
        ], "edges": [{"source": "t", "port": "out", "target": "s"}, {"source": "s", "port": "out", "target": "v"}],
    }), admin.id)
    scope = validation.DraftScope(project_id=project.id)
    verdict = await validation.run_graphs(db, draft.id, scope, await validation.governing_graphs(db, scope))
    assert [f.message for f in verdict.findings] == [f"Draft: {secret.title}"]
    submitter = User(email=f"submitter-{uuid.uuid4().hex}@example.com", name="Submitter", instance_role="member")
    role = Role(key=f"submit_{uuid.uuid4().hex}", name="Submitter", permissions=["item.create", "item.read"])
    db.add_all([submitter, role])
    await db.flush()
    db.add(GlobalRoleGrant(user_id=submitter.id, role_id=role.id, project_id=project.id))
    await db.flush()
    with pytest.raises(NotFoundError):
        await items.get_item(db, secret.id, submitter)
    outcome = await intake.validate_and_create(db, ItemCreate(project_id=project.id, title="Member request"), submitter)
    assert [f.message for f in outcome.verdict.findings] == [f"Draft: {secret.title}"]


async def test_resolution_template_does_not_bind_automated_changes(world):
    from radd.modules.mailintake.templates import TELL_REQUESTER_WHEN_RESOLVED as template
    db, admin, _ = world
    rule = await automations.create_rule(db, RuleCreate(name=template.name, nodes=list(template.nodes), edges=list(template.edges)), admin.id)
    assert rule.enabled
    assert rule.id in [r.id for r, _ in await automations.rules_for_trigger(db, "item.updated")]
    assert rule.id not in [r.id for r, _ in await automations.rules_for_trigger(db, "item.updated", automated=True)]


def test_migration_promotes_shared_advisory_branch_to_required():
    path = Path(__file__).parents[2] / "server/migrations/versions/d1329verdict_validation_verdict_nodes.py"
    spec = importlib.util.spec_from_file_location("review_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    nodes = [
        {"id": mode, "kind": "trigger", "type": "trigger.event", "params": {"event": "validate", "mode": mode, "targets": [{"kind": "project", "id": str(uuid.uuid4())}]}}
        for mode in ("advisory", "required")
    ] + [{"id": "f", "kind": "action", "type": "validation.fail", "params": {"message": "Check"}}]
    edges = [{"source": mode, "port": "out", "target": "f"} for mode in ("advisory", "required")]
    _, _, can_block = migration.rewrite(nodes, edges)
    assert can_block == {"advisory": True, "required": True}


async def test_plugin_renderer_discards_missing_variable_failure(world):
    from radd.modules.automations.executor import _NodeContext
    from radd.modules.automations.graph import Node, Packet
    from radd.modules.automations.planning import _manual_facts
    from radd.modules.automations.types import AutomationNodeKind
    from radd.modules.releases.automation import plan_publish, apply_publish
    from radd.modules.releases.models import Release
    db, admin, project = world
    ctx = _NodeContext(session=db, node=Node(id="c", kind=AutomationNodeKind.ACTION, type="page.comment", params={"body": "{{classify.answer}}"}), packet=Packet.of(_manual_facts()), actor=admin)
    # Renderer keeps the literal and throws away Renderer.misses.
    assert await ctx.render("{{classify.answer}}") == "{{classify.answer}}"
    ctx.node = Node(id="r", kind=AutomationNodeKind.ACTION, type="release.publish", params={"project": project.key, "version": "{{classify.answer}}"})
    plan = await plan_publish(ctx)
    assert plan.resolves and plan.version == "{{classify.answer}}"
    await apply_publish(ctx, plan)
    assert await db.scalar(select(Release).where(Release.project_id == project.id, Release.version == "{{classify.answer}}")) is not None


async def test_watch_trigger_can_recreate_itself_past_chain_limit(world):
    from radd.modules.notify import consumer
    db, admin, project = world
    rule = await automations.create_rule(db, RuleCreate.model_validate({
        "name": "Follow up when watched", "nodes": [
            {"id": "t", "kind": "trigger", "type": "trigger.event", "params": {"event": "item.watched"}},
            {"id": "c", "kind": "action", "type": "action.create_item", "params": {"project": project.key, "title": "Follow up"}},
        ], "edges": [{"source": "t", "port": "out", "target": "c"}],
    }), admin.id)
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="Start"), admin)
    original = await db.scalar(select(Event).where(Event.event_type == "item.created", Event.entity_id == str(item.id)).order_by(Event.id.desc()).limit(1))
    for _ in range(settings.automation_max_chain_depth + 2):
        await consumer._handle(db, original, watch_only=False)
        watched = await db.scalar(select(Event).where(Event.event_type == "item.watched", Event.entity_id == original.entity_id).order_by(Event.id.desc()).limit(1))
        assert watched is not None and not watched.automated
        await engine.apply_event(db, watched)
        created = await db.scalar(select(Event).where(Event.event_type == "item.created", Event.id > watched.id).order_by(Event.id.desc()).limit(1))
        assert created is not None and created.automation_rule_id == rule.id
        assert created.automation_depth == 1
        original = created


async def test_state_category_gate_accepts_manual_rule_but_never_reads_seed_state(world):
    from radd.modules.automations.gates import state_category_is
    from radd.modules.workflow.models import State
    db, admin, project = world
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="Seed"), admin)
    row = await items.require_item(db, item.id)
    state = await db.get(State, row.state_id)
    await automations.create_rule(db, RuleCreate.model_validate({
        "name": "Manual category", "nodes": [
            {"id": "t", "kind": "trigger", "type": "trigger.event", "params": {"event": "manual"}},
            {"id": "g", "kind": "gate", "type": "gate.state_category", "params": {"categories": [state.category]}},
        ], "edges": [{"source": "t", "port": "out", "target": "g"}],
    }), admin.id)
    facts = await engine._seeded_facts(db, "item", item.id)
    assert state_category_is(facts, {"categories": [state.category]}) is False


async def test_saved_graph_publishes_literal_after_classifier_unavailable(world, monkeypatch):
    from radd.modules.ai import automation_node
    from radd.modules.releases.models import Release
    db, admin, project = world
    async def unavailable(*args, **kwargs):
        return "unavailable"
    monkeypatch.setattr(automation_node, "_ask", unavailable)
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="Seed"), admin)
    rule = await automations.create_rule(db, RuleCreate.model_validate({
        "name": "Publish after fallback", "nodes": [
            {"id": "t", "kind": "trigger", "type": "trigger.event", "params": {"event": "manual"}},
            {"id": "c", "name": "classify", "kind": "gate", "type": "ai.classify", "params": {"prompt": "Choose version", "answers": ["1.0", "2.0"]}},
            {"id": "p", "kind": "action", "type": "release.publish", "params": {"project": project.key, "version": "{{classify.answer}}"}},
        ], "edges": [{"source": "t", "port": "out", "target": "c"}, {"source": "c", "port": "unavailable", "target": "p"}],
    }), admin.id)
    assert await engine.run_manual(db, rule, item.id)
    assert await db.scalar(select(Release).where(Release.project_id == project.id, Release.version == "{{classify.answer}}")) is not None


async def test_deleting_last_seed_receiver_recreates_it(world, monkeypatch):
    from contextlib import asynccontextmanager
    from radd.modules.alertmanager import service
    from radd.modules.alertmanager.models import AlertReceiver
    db, _, _ = world
    assert list((await db.scalars(select(AlertReceiver))).all()) == []
    @asynccontextmanager
    async def borrowed_session():
        yield db
    monkeypatch.setattr(service, "SessionLocal", borrowed_session)
    # Exercise startup seeding without committing outside this rollback fixture.
    monkeypatch.setattr(db, "commit", db.flush)
    token = uuid.uuid4().hex
    monkeypatch.setattr(settings, "alertmanager_token", token)
    monkeypatch.setattr(settings, "alertmanager_project_key", "")
    await service.seed_from_env()
    first = await db.scalar(select(AlertReceiver).where(AlertReceiver.token == token))
    first_id = first.id
    await service.delete_receiver(db, first_id)
    await service.seed_from_env()
    recreated = await db.scalar(select(AlertReceiver).where(AlertReceiver.token == token))
    assert recreated is not None and recreated.active and recreated.id != first_id


async def test_private_search_candidates_hide_readable_milestone(world):
    from radd.kernel import entities as kentities
    from radd.kernel.registry import registries
    from radd.modules.auth.models import Role, GlobalRoleGrant
    from radd.modules.milestones import plugin
    db, _, project = world
    registries.register_plugin(plugin)
    for spec in plugin.entities:
        kentities.register_entity(spec)
    await kentities.ensure_tables()
    outsider = User(email=f"review-member-{uuid.uuid4().hex}@example.com", name="Member", instance_role="member")
    role = Role(key=f"review_{uuid.uuid4().hex}", name="Review reader", permissions=["item.read"])
    db.add_all([outsider, role])
    await db.flush()
    db.add(GlobalRoleGrant(user_id=outsider.id, role_id=role.id, project_id=project.id))
    hidden = await projects.create_project(db, ProjectCreate(key=f"RH{uuid.uuid4().hex[:5].upper()}", name="Hidden"))
    model = kentities.model_for("milestone")
    word = f"Review{uuid.uuid4().hex}"
    visible = model(project_id=project.id, title=f"{word} Z visible", status="open")
    db.add(visible)
    db.add_all([model(project_id=hidden.id, title=f"{word} A{i:02}", status="open") for i in range(25)])
    await db.flush()
    search = registries.searchables["milestone"].search
    assert [hit["id"] for hit in await search(db, outsider, f"{word} Z", limit=5)] == [str(visible.id)]
    assert await search(db, outsider, word, limit=5) == []
