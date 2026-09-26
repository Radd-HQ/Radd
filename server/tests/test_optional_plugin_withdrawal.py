"""RADD-1387 — core modules stop reaching into optional plugins.

`automations` imported `leave`, `mailintake` and `participants`, and
`attachments` imported `ai`, each behind a `settings.modules` check or a
`plugin_loaded()` guard. `settings.modules` is BOOT config: a plugin disabled at
runtime leaves the kernel registries, and those calls kept running. Each reach
is now something the optional plugin CONTRIBUTES, so withdrawing the plugin
withdraws the behaviour. This module pins both halves against the real plugins,
withdrawn the way the plugin manager does it (`registries.unregister_plugin`):

* round-robin asks the PERSON_AVAILABILITY socket — leave withdrawn, nobody is
  away (and nothing crashes); registered, the away member is skipped;
* Send email (and Add participant) are nodes mailintake (participants)
  contribute under the keys they always had — a graph STORED before the move
  loads and dry-runs unchanged; withdrawn, the node leaves the catalog and the
  stored graph reports the engine's unknown-action failure for that node;
* the `llm` storage routing rule is ai's provider on STORAGE_ROUTING_RULE —
  withdrawn, the type is not offered, a new one is refused, and a stored one
  falls through to the default host.

DB-backed, flushed never committed; the session rolls back at teardown.
"""

import importlib
import uuid
from contextlib import contextmanager
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.kernel.registry import registries
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole

automations_router = importlib.import_module("radd.modules.automations.router")


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def admin(db) -> User:
    user = User(
        email=f"withdraw-{uuid.uuid4().hex[:8]}@example.com",
        name="Withdraw Admin",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


@contextmanager
def withdrawn(name: str):
    """The plugin gone from the kernel registries, as a runtime disable leaves it."""
    plugin = registries.plugins[name]
    registries.unregister_plugin(plugin)
    try:
        yield
    finally:
        registries.register_plugin(plugin)


def test_the_core_modules_declare_no_edge_to_the_plugins():
    """The imports are gone, so the declarations went with them — and
    test_module_contracts refuses any import that comes back undeclared."""
    from radd.modules.attachments import plugin as attachments
    from radd.modules.automations import plugin as automations

    reach = set(automations.depends_on) | set(automations.weak_depends)
    assert not reach & {"leave", "mailintake", "participants"}
    assert "ai" not in set(attachments.depends_on) | set(attachments.weak_depends)


# --- round-robin: who is away ------------------------------------------------


async def test_round_robin_skips_the_away_only_while_leave_provides_it(db, admin):
    from radd.modules.automations import round_robin
    from radd.modules.leave import service as leave_service
    from radd.modules.leave.schemas import LeaveCreate
    from radd.modules.teams import service as teams_service
    from radd.modules.teams.schemas import TeamCreate

    team = await teams_service.create_team(
        db, TeamCreate(name=f"Withdraw {uuid.uuid4().hex[:6]}"), actor_id=admin.id
    )
    members = []
    for n in range(2):
        member = User(email=f"rr-w-{uuid.uuid4().hex[:8]}@example.com", name=f"Member {n}")
        db.add(member)
        await db.flush()
        await teams_service.add_team_member(db, team.id, member.id, actor_id=admin.id)
        members.append(member)
    first, second = sorted(members, key=lambda user: user.id)
    today = date.today()
    await leave_service.create(
        db, admin, LeaveCreate(user_id=first.id, label="ooo", start_date=today, end_date=today)
    )
    await db.flush()

    # Registered: the away member is passed over.
    assert await round_robin.away_user_ids(db, today, [first.id, second.id]) == {first.id}
    assert await round_robin.pick_next(db, team) == second.id

    # Withdrawn: no provider answers, so nobody is away — degraded, not crashed.
    with withdrawn("leave"):
        assert await round_robin.away_user_ids(db, today, [first.id, second.id]) == set()
        assert await round_robin.pick_next(db, team) == first.id


# --- Send email / Add participant: contributed nodes, same keys ---------------


async def _legacy_rule(db, admin):
    """A graph as STORED before RADD-1387 — written straight to the row, no API,
    exactly the shape the built-in actions saved."""
    from radd.modules.automations.models import Automation

    rule = Automation(
        name=f"legacy-{uuid.uuid4().hex[:6]}",
        enabled=False,
        created_by_id=admin.id,
        nodes=[
            {"id": "t", "kind": "trigger", "type": "trigger.event", "params": {"event": "item.created"}},
            {"id": "mail", "kind": "action", "type": "action.send_email",
             "params": {"to": "reporter", "arity": "item", "subject": "{{item.key}}", "body": "Hello"}},
            {"id": "share", "kind": "action", "type": "action.add_participant",
             "params": {"user": admin.email}},
        ],
        edges=[
            {"source": "t", "port": "out", "target": "mail"},
            {"source": "t", "port": "out", "target": "share"},
        ],
    )
    db.add(rule)
    await db.flush()
    return rule


async def _item(db, admin):
    from radd.modules.items import service as items_service
    from radd.modules.items.schemas import ItemCreate
    from radd.modules.projects import service as projects_service
    from radd.modules.projects.schemas import ProjectCreate

    project = await projects_service.create_project(
        db, ProjectCreate(key=f"WD{uuid.uuid4().hex[:4].upper()}", name="Withdrawal")
    )
    return await items_service.create_item(db, ItemCreate(project_id=project.id, title="t"), admin)


def _by_node(result) -> dict:
    return {preview.node_id: preview for preview in result.would_apply}


async def test_stored_graphs_keep_their_nodes_and_report_a_withdrawn_owner(db, admin, monkeypatch):
    from radd.modules.automations import engine, runs
    from radd.modules.mailintake import service as mail_service

    async def configured(_session):
        return True

    monkeypatch.setattr(mail_service, "outbound_configured", configured)
    rule = await _legacy_rule(db, admin)
    item = await _item(db, admin)

    # Registered: the catalog offers both under the old keys, owned by the
    # plugins, and the stored graph dry-runs exactly as it did when built in.
    catalog = {node.key: node.plugin for node in (await automations_router.get_catalog(db, admin)).nodes}
    assert catalog["action.send_email"] == "mailintake"
    assert catalog["action.add_participant"] == "participants"
    planned = _by_node(await engine.preview(db, rule, item.id))
    assert planned["mail"].resolves and planned["mail"].detail == f"send_email -> {admin.email}"
    assert planned["share"].resolves and planned["share"].detail == f"add_participant {admin.email}"

    with withdrawn("mailintake"):
        catalog = {node.key for node in (await automations_router.get_catalog(db, admin)).nodes}
        assert "action.send_email" not in catalog
        # The stored graph still LOADS; the orphaned node fails loudly, its
        # sibling is untouched.
        planned = _by_node(await engine.preview(db, rule, item.id))
        assert planned["mail"].failed and "unknown action type 'action.send_email'" in planned["mail"].detail
        assert planned["share"].resolves
        # An APPLYING walk is recorded as failed, naming the node — nothing is
        # sent (the node is gone), nothing raises into the consumer.
        from radd.modules.automations.graph import Packet

        report = await engine.run_graph(
            db, rule, Packet.of(engine._manual_facts(), item=[item.id]), admin, apply=True
        )
        assert report is not None
        (run,) = await runs.list_runs(db, rule.id)
        assert run.status == "failed" and "action.send_email" in run.error

    with withdrawn("participants"):
        assert "action.add_participant" not in {
            node.key for node in (await automations_router.get_catalog(db, admin)).nodes
        }
        planned = _by_node(await engine.preview(db, rule, item.id))
        assert planned["share"].failed and "action.add_participant" in planned["share"].detail


async def test_a_withdrawn_node_cannot_be_saved(db, admin):
    from radd.exceptions import ConflictError
    from radd.modules.automations import service as automations
    from radd.modules.automations.schemas import RuleCreate

    graph = RuleCreate.model_validate({
        "name": f"new-{uuid.uuid4().hex[:6]}",
        "enabled": False,
        "nodes": [
            {"id": "t", "kind": "trigger", "type": "trigger.event", "params": {"event": "item.created"}},
            {"id": "mail", "kind": "action", "type": "action.send_email",
             "params": {"to": "ops@example.com", "subject": "s", "body": "b"}},
        ],
        "edges": [{"source": "t", "port": "out", "target": "mail"}],
    })
    with withdrawn("mailintake"):
        with pytest.raises(ConflictError, match="not a node type this server offers"):
            await automations.create_rule(db, graph, admin.id)
    assert (await automations.create_rule(db, graph, admin.id)).id is not None


# --- the llm storage routing rule --------------------------------------------


async def test_the_llm_routing_rule_is_offered_and_run_only_while_ai_provides_it(
    db, admin, tmp_path, monkeypatch
):
    from radd.modules.ai import client as ai_client, features as ai_features
    from radd.modules.ai.types import StorageRuleType
    from radd.modules.attachments import hosts
    from radd.modules.attachments.routing import engine, store
    from radd.modules.attachments.routing.context import RoutingContext
    from radd.modules.attachments.schemas import StorageHostCreate
    from radd.modules.attachments.types import (
        AttachmentParentType, DeliveryMode, RuleType, StorageHostType,
    )

    async def host(name: str, **flags):
        return await hosts.create_host(db, StorageHostCreate(
            name=f"{name}-{uuid.uuid4().hex[:6]}", host_type=StorageHostType.FILESYSTEM,
            root_dir=str(tmp_path / name), delivery_mode=DeliveryMode.PROXY, **flags,
        ))

    default = await host("default", is_default=True)
    content = await host("content", user_selectable=True)
    llm = StorageRuleType.LLM.value
    config = {
        "prompt": "classify",
        "answers": [
            {"answer": "content", "host_id": str(content.id)},
            {"answer": "general", "host_id": str(default.id)},
        ],
    }
    calls = []

    async def classify(session, role, **kwargs):
        calls.append(role)
        return "content"

    async def feature_on(session, feature):
        return True

    monkeypatch.setattr(ai_client, "complete_choice", classify)
    monkeypatch.setattr(ai_features, "feature_enabled", feature_on)
    await store.create_rule(db, name="Classify", rule_type=llm, config=config)
    await store.create_rule(db, name="Ask", rule_type=RuleType.USER_CHOICE, config={})
    ctx = RoutingContext(
        actor_id=admin.id, source_ip=None, chosen_host_id=None, filename="f.png",
        content_type="image/png", size_bytes=3, entity_type=AttachmentParentType.ITEM.value,
        entity_id=uuid.uuid4(), project_id=None, content=lambda: b"png",
    )

    # Registered: offered, it decides images, and it pre-empts the ask for them.
    assert llm in store.rule_types()
    assert (await engine.decide(db, ctx)).id == content.id
    assert await engine.choice_reachable(db, source_ip=None, content_types=["image/png"]) == (False, "Classify")

    with withdrawn("ai"):
        assert llm not in store.rule_types()
        assert {RuleType.USER_CHOICE.value, RuleType.CIDR.value} <= set(store.rule_types())
        with pytest.raises(store.RuleConfigError):
            await store.create_rule(db, name="Again", rule_type=llm, config=config)
        # The stored rule has no provider: skipped, the chain falls through to
        # the default, the model is never asked, and the uploader is asked.
        calls.clear()
        assert (await engine.decide(db, ctx)).id == default.id
        assert calls == []
        assert await engine.choice_reachable(db, source_ip=None, content_types=["image/png"]) == (True, None)

    assert (await engine.decide(db, ctx)).id == content.id
