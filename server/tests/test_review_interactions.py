"""Regression coverage for the interactions found in the September review.
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


async def test_receivers_isolate_issues_across_projects(world):
    from radd.modules.alertmanager import service
    from radd.modules.alertmanager.schemas import ReceiverCreate
    db, admin, project = world
    other = await projects.create_project(db, ProjectCreate(key=f"RX{uuid.uuid4().hex[:5].upper()}", name="Other"))
    receivers = [await service.create_receiver(db, ReceiverCreate(name=uuid.uuid4().hex, token=uuid.uuid4().hex, project_id=p.id)) for p in (project, other)]
    fingerprint = uuid.uuid4().hex
    payload = {"alerts": [{"status": "firing", "fingerprint": fingerprint, "labels": {"alertname": "DiskFull"}}]}
    assert (await service.process(db, receivers[0], payload))["created"] == 1
    assert (await service.process(db, receivers[1], payload))["created"] == 1
    await service.process(db, receivers[1], payload)
    event = await db.scalar(select(Event).where(Event.event_type == "alertmanager.alert.repeated").order_by(Event.id.desc()).limit(1))
    target = await items.require_item(db, uuid.UUID(event.payload["item"]["id"]))
    assert target.project_id == receivers[1].project_id != project.id
    payload["alerts"][0]["status"] = "resolved"
    await service.process(db, receivers[1], payload)
    resolved = await db.scalar(select(Event).where(Event.event_type == "alertmanager.alert.resolved").order_by(Event.id.desc()).limit(1))
    assert resolved.payload["item"]["id"] == str(target.id)


async def test_auto_watch_preserves_automation_cause(world):
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
    assert watched.automated and watched.automation_depth == cause.depth and watched.automation_rule_id == cause.rule_id
    assert not engine.should_process(watched)


async def test_verdict_item_tokens_always_describe_original_draft(world):
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
    assert [f.message for f in verdict.findings] == ["Draft: Public request"]
    submitter = User(email=f"submitter-{uuid.uuid4().hex}@example.com", name="Submitter", instance_role="member")
    role = Role(key=f"submit_{uuid.uuid4().hex}", name="Submitter", permissions=["item.create", "item.read"])
    db.add_all([submitter, role])
    await db.flush()
    db.add(GlobalRoleGrant(user_id=submitter.id, role_id=role.id, project_id=project.id))
    await db.flush()
    with pytest.raises(NotFoundError):
        await items.get_item(db, secret.id, submitter)
    outcome = await intake.validate_and_create(db, ItemCreate(project_id=project.id, title="Member request"), submitter)
    assert [f.message for f in outcome.verdict.findings] == ["Draft: Member request"]


async def test_resolution_node_binds_automated_changes(world):
    db, admin, _ = world
    nodes = [
        {"id": "trg", "kind": "trigger", "type": "trigger.event", "params": {"event": "item.updated", "include_automated": True}},
        {"id": "notice", "kind": "action", "type": "mailintake.notify_resolution", "params": {}},
    ]
    edges = [{"source": "trg", "port": "out", "target": "notice"}]
    rule = await automations.create_rule(db, RuleCreate(name="Resolution", nodes=nodes, edges=edges), admin.id)
    assert rule.enabled
    assert rule.id in [r.id for r, _ in await automations.rules_for_trigger(db, "item.updated")]
    assert rule.id in [r.id for r, _ in await automations.rules_for_trigger(db, "item.updated", automated=True)]


def test_migration_preserves_shared_advisory_branch_policy():
    path = Path(__file__).parents[1] / "migrations/versions/d1329verdict_validation_verdict_nodes.py"
    spec = importlib.util.spec_from_file_location("review_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    nodes = [
        {"id": mode, "kind": "trigger", "type": "trigger.event", "params": {"event": "validate", "mode": mode, "targets": [{"kind": "project", "id": str(uuid.uuid4())}]}}
        for mode in ("advisory", "required")
    ] + [{"id": "f", "kind": "action", "type": "validation.fail", "params": {"message": "Check"}}]
    edges = [{"source": mode, "port": "out", "target": "f"} for mode in ("advisory", "required")]
    _, _, can_block = migration.rewrite(nodes, edges)
    assert can_block == {"advisory": False, "required": True}




async def test_watch_trigger_cannot_recreate_itself(world):
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
    await consumer._handle(db, original, watch_only=False)
    watched = await db.scalar(select(Event).where(Event.event_type == "item.watched", Event.entity_id == original.entity_id).order_by(Event.id.desc()).limit(1))
    await engine.apply_event(db, watched)
    created = await db.scalar(select(Event).where(Event.event_type == "item.created", Event.id > watched.id).order_by(Event.id.desc()).limit(1))
    await consumer._handle(db, created, watch_only=False)
    derived = await db.scalar(select(Event).where(Event.event_type == "item.watched", Event.entity_id == created.entity_id).order_by(Event.id.desc()).limit(1))
    assert derived.automated and derived.automation_rule_id == rule.id
    await engine.apply_event(db, derived)
    assert await db.scalar(select(Event).where(Event.event_type == "item.created", Event.id > derived.id)) is None


async def test_state_category_gate_reads_seed_state(world):
    from radd.modules.automations.builtin_routers import _state_categories
    from radd.modules.automations.executor import _NodeContext
    from radd.modules.automations.graph import Node, Packet
    from radd.modules.automations.types import AutomationNodeKind
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
    ctx = _NodeContext(session=db, actor=admin, node=Node(id="g", kind=AutomationNodeKind.GATE, type="gate.state_category", params={"categories": [state.category]}), packet=Packet.of(facts, item=(item.id,)))
    assert await _state_categories(ctx) == {item.id: "true"}


async def test_saved_graph_skips_publish_after_classifier_unavailable(world, monkeypatch):
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
    assert not await engine.run_manual(db, rule, item.id)
    assert await db.scalar(select(Release).where(Release.project_id == project.id, Release.version == "{{classify.answer}}")) is None


async def test_deleting_last_seed_receiver_stays_deleted(world, monkeypatch):
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
    # By the token's OWNER, not its value: the column is ciphertext under a fresh
    # nonce, so no SQL predicate can find it; `receiver_for_token` decrypts.
    first = await service.receiver_for_token(db, token)
    first_id = first.id
    await service.delete_receiver(db, first_id)
    await service.seed_from_env()
    assert await service.receiver_for_token(db, token) is None
    assert list((await db.scalars(select(AlertReceiver))).all()) == []


async def test_private_search_candidates_do_not_hide_readable_milestone(world):
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
    assert [hit["id"] for hit in await search(db, outsider, word, limit=5)] == [str(visible.id)]


async def test_resolution_mail_keeps_lifecycle_contacts_and_csat_policy(world, monkeypatch):
    from types import SimpleNamespace
    from radd.modules.mailintake import automation, resolved, service as mail
    from radd.modules.workflow.models import State
    db, admin, project = world
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="Request"), admin)
    await mail.upsert_contact(db, item.id, email="requester@example.test")
    await mail.upsert_contact(db, item.id, email="copied@example.test", copied_in=True)
    await mail.upsert_contact(db, item.id, email=admin.email, copied_in=True)
    states = list((await db.scalars(select(State).where(State.project_id == project.id))).all())
    done = next(s for s in states if s.category == "done")
    todo = next(s for s in states if s.category != "done")
    payload = {"item": {"id": str(item.id), "state": {"name": done.name, "category": "done"}},
               "changes": [{"field": "state", "from": todo.name, "to": done.name}]}
    ctx = SimpleNamespace(session=db, actor=admin, subject_ids=(item.id,), packet=SimpleNamespace(facts=SimpleNamespace(payload=payload)))
    async def available(*args, **kwargs): return True
    async def no_survey(*args, **kwargs): return False
    monkeypatch.setattr(mail, "outbound_configured", available)
    monkeypatch.setattr(resolved, "_csat_announces", no_survey)
    # The node runs whatever the `mail_send_resolved` setting says (default OFF).
    plan = await automation.plan_resolution(ctx)
    assert plan.resolves and {r.email for r in plan.notice.recipients} == {"requester@example.test", "copied@example.test"}
    delivered = []
    async def send(*args, **kwargs): delivered.append(kwargs)
    monkeypatch.setattr(mail, "send_item_mail", send)
    await automation.apply_resolution(ctx, plan)
    assert len(delivered) == 2 and all(m["item_id"] == item.id for m in delivered)
    payload["changes"][0]["from"] = done.name
    assert not (await automation.plan_resolution(ctx)).resolves
    payload["changes"][0]["from"] = todo.name
    monkeypatch.setattr(resolved, "_csat_announces", available)
    assert not (await automation.plan_resolution(ctx)).resolves


async def test_watcher_bootstrap_emits_only_silent_derived_events(world):
    from radd.modules.notify import consumer
    db, admin, project = world
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="Historical"), admin)
    original = await db.scalar(select(Event).where(Event.event_type == "item.created", Event.entity_id == str(item.id)).order_by(Event.id.desc()).limit(1))
    await consumer._handle(db, original, watch_only=True)
    watched = await db.scalar(select(Event).where(Event.event_type == "item.watched", Event.entity_id == str(item.id)).order_by(Event.id.desc()).limit(1))
    assert watched.silent and not engine.should_process(watched)


async def test_ci_ignores_old_runs_and_repeated_outcomes(world):
    from radd.modules.vcs import service as vcs
    from radd.modules.vcs.schemas import VcsLinkCreate
    from radd.modules.vcs.types import VcsProvider, VcsRefType
    db, admin, project = world
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="CI"), admin)
    link = await vcs.link_vcs(db, item.id, VcsLinkCreate(provider=VcsProvider.GITLAB, ref_type=VcsRefType.BRANCH,
        title="main", url="https://git.example/project", external_id=f"branch:{project.key}:main"))
    args = dict(provider="gitlab", external_ids=[link.external_id])
    assert len(await vcs.set_ci_state(db, **args, ci_state="running", run_id=20)) == 1
    assert len(await vcs.set_ci_state(db, **args, ci_state="success", run_id=20)) == 1
    assert await vcs.set_ci_state(db, **args, ci_state="success", run_id=20) == []
    assert await vcs.set_ci_state(db, **args, ci_state="failure", run_id=19) == []
    assert await vcs.set_ci_state(db, **args, ci_state="running", run_id=20) == []
    assert link.ci_state == "success" and link.ci_run_id == 20
    assert len(await vcs.set_ci_state(db, **args, ci_state="running", run_id=21)) == 1


async def test_webhook_delivery_claims_are_scoped_and_transactional(world):
    from radd.modules.vcs.receiving import claim_delivery
    db, _, _ = world
    args = dict(provider="gitlab", connection_id=uuid.uuid4(), delivery_id="delivery-1", event_type="merge_request", body=b'{"action":"update"}')
    nested = await db.begin_nested()
    assert await claim_delivery(db, **args)
    assert not await claim_delivery(db, **args)
    await nested.rollback()
    assert await claim_delivery(db, **args), "rolled-back effects must be retryable"
    assert await claim_delivery(db, **{**args, "connection_id": uuid.uuid4()})
    assert await claim_delivery(db, **{**args, "delivery_id": "delivery-2"})


async def test_notification_kinds_fan_out_even_for_core_events(world, monkeypatch):
    from radd.kernel import NotificationKindSpec, registries
    from radd.modules.notify import consumer
    db, admin, project = world
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="Fanout"), admin)
    event = await db.scalar(select(Event).where(Event.event_type == "item.created", Event.entity_id == str(item.id)).order_by(Event.id.desc()).limit(1))
    seen = []
    async def recipients(*args): return []
    async def handle(session, event, spec): seen.append(spec.key)
    monkeypatch.setattr(consumer, "_handle_contributed", handle)
    for key in ("review.one", "review.two"):
        monkeypatch.setitem(registries.notification_kinds, key, NotificationKindSpec(key=key, label=key,
            events=("item.created",), recipients=recipients))
    await consumer._handle(db, event, watch_only=False)
    assert seen == ["review.one", "review.two"]


async def test_consumer_preserves_cause_during_planning_and_delivery(world, monkeypatch):
    from contextlib import asynccontextmanager
    from radd.modules.events import runner
    db, admin, project = world
    cause = events.AutomationCause(rule_id=uuid.uuid4(), depth=2)
    with events.automated(cause=cause):
        item = await items.create_item(db, ItemCreate(project_id=project.id, title="Derived"), admin)
    original = await db.scalar(select(Event).where(Event.event_type == "item.created", Event.entity_id == str(item.id)).order_by(Event.id.desc()).limit(1))
    @asynccontextmanager
    async def borrowed(): yield db
    async def exists(*args): return True
    async def offset(*args): return 0
    async def read(*args): return [original]
    async def advance(*args): pass
    monkeypatch.setattr(runner, "SessionLocal", borrowed)
    monkeypatch.setattr(db, "commit", db.flush)
    monkeypatch.setattr(events, "offset_exists", exists)
    monkeypatch.setattr(events, "get_offset", offset)
    monkeypatch.setattr(events, "read_after", read)
    monkeypatch.setattr(events, "set_offset", advance)
    seen = []
    async def plan(session, event):
        seen.append(events.current_cause())
        return "mail"
    async def deliver(plans):
        assert plans == ["mail"]
        seen.append(events.current_cause())
    assert await runner.run_head_seeded("review", batch_size=10, plan=plan, deliver=deliver) == 1
    assert seen == [cause, cause]
    assert events.current_cause() is None


async def test_declared_optional_paths_remain_after_samples_exist(world, monkeypatch):
    from types import SimpleNamespace
    import importlib
    router = importlib.import_module("radd.modules.automations.router")
    db, admin, _ = world
    async def recent(*args, **kwargs): return [SimpleNamespace(payload={"repo": "org/project"})]
    monkeypatch.setattr(router.events_service, "query_events", recent)
    read = await router.event_samples("gitlab.merge_request.merged", db, admin, limit=10)
    assert read.sampled == 1
    assert "ref.source_branch" in {entry.path for entry in read.declared_paths}


def test_related_record_findings_cannot_quote_private_content():
    from radd.modules.automations.executor import _NodeContext
    from radd.modules.automations.graph import Node, Packet
    from radd.modules.automations.planning import _manual_facts
    from radd.modules.automations.types import AutomationNodeKind
    ctx = _NodeContext(session=None, actor=None, findings=[], draft_id=uuid.uuid4(), published={},
        node=Node(id="check", kind=AutomationNodeKind.GATE, type="ai.validate", params={}),
        packet=Packet.of(_manual_facts(), item=(uuid.uuid4(),)))
    ctx.publish_findings([{"message": "Private title", "field": "description", "blocking": True}])
    found = ctx.published_by("check")
    assert found[0]["blocking"] and "Private title" not in found[0]["message"]
    assert found[0]["field"] == ""
