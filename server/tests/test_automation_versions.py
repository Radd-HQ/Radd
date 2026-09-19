"""Versioned automations (RADD-1268, delivering RADD-1111): every save that
changes what the automation IS writes an immutable version; a toggle does not;
restoring writes a NEW version copying the old one and rebuilds the bindings;
the ledger says which version a change made."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import ConflictError
from radd.modules.auth.models import User
from radd.modules.automations import service as automations, versions
from radd.modules.automations.models import TriggerBinding
from radd.modules.automations.schemas import RuleCreate, RuleUpdate
from radd.modules.events import service as events


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
    user = User(email=f"ver-{uuid.uuid4().hex[:8]}@example.com", name="Version Admin", instance_role="admin")
    db.add(user)
    await db.flush()
    return user


def _graph(event: str, label: str, note: str = "") -> dict:
    return {
        "name": "versioned",
        "note": note,
        "nodes": [
            {"id": "trg", "kind": "trigger", "type": "trigger.event", "params": {"event": event}},
            {"id": "act", "kind": "action", "type": "action.add_label", "params": {"label": label}},
        ],
        "edges": [{"source": "trg", "port": "out", "target": "act"}],
    }


async def test_every_content_change_is_a_version_and_a_toggle_is_not(db, admin):
    rule = await automations.create_rule(db, RuleCreate.model_validate(_graph("item.created", "one", "first")), admin.id)
    assert rule.version == 1
    rows = await versions.list_versions(db, rule.id)
    assert [row.version for row in rows] == [1] and rows[0].note == "first"

    g2 = _graph("item.created", "two")
    await automations.update_rule(db, rule.id, RuleUpdate(nodes=g2["nodes"], edges=g2["edges"], note="relabel"), admin.id)
    assert rule.version == 2
    await automations.update_rule(db, rule.id, RuleUpdate(name="renamed"), admin.id)
    assert rule.version == 3
    await automations.update_rule(db, rule.id, RuleUpdate(enabled=False), admin.id)
    await automations.update_rule(db, rule.id, RuleUpdate(position=7), admin.id)
    assert rule.version == 3, "enabled and position are not what the automation is"

    rows = await versions.list_versions(db, rule.id)
    assert [row.version for row in rows] == [3, 2, 1]
    assert rows[1].note == "relabel" and rows[1].nodes[1]["params"]["label"] == "two"
    assert rows[0].name == "renamed" and rows[2].name == "versioned"


async def test_restore_writes_a_new_version_copying_the_old_and_rebuilds_the_bindings(db, admin):
    rule = await automations.create_rule(db, RuleCreate.model_validate(_graph("item.created", "one")), admin.id)
    g2 = _graph("comment.created", "two")
    await automations.update_rule(db, rule.id, RuleUpdate(nodes=g2["nodes"], edges=g2["edges"], name="second"), admin.id)
    assert rule.version == 2
    bound = (await db.execute(select(TriggerBinding.event_type).where(TriggerBinding.automation_id == rule.id))).scalars().all()
    assert bound == ["comment.created"]

    head = (await db.execute(select(events.Event.id).order_by(events.Event.id.desc()).limit(1))).scalar() or 0
    restored = await automations.restore_version(db, rule.id, 1, admin.id, note="back to one")
    assert restored.version == 3
    assert restored.name == "versioned"
    assert restored.nodes[0]["params"]["event"] == "item.created"
    assert restored.nodes[1]["params"]["label"] == "one"
    rows = await versions.list_versions(db, rule.id)
    assert [row.version for row in rows] == [3, 2, 1]
    assert rows[0].restored_from == 1 and rows[0].note == "back to one"
    assert rows[0].nodes == rows[2].nodes and rows[0].edges == rows[2].edges
    # v2 is still there, untouched: history never rewrites.
    assert rows[1].name == "second"
    # The engine's index follows the restored graph.
    bound = (await db.execute(select(TriggerBinding.event_type).where(TriggerBinding.automation_id == rule.id))).scalars().all()
    assert bound == ["item.created"]
    # The ledger names the version the restore made.
    updated = [e for e in await events.read_after(db, head, 50) if e.event_type == "automation.updated"]
    assert updated, "the restore emits automation.updated"
    changed = {c["field"]: c for c in updated[-1].payload["changes"]}
    assert changed["version"]["from"] == 2 and changed["version"]["to"] == 3


async def test_restoring_a_graph_that_no_longer_validates_is_refused(db, admin):
    rule = await automations.create_rule(db, RuleCreate.model_validate(_graph("item.created", "one")), admin.id)
    # Hand-edit v1 into something the validator refuses (an unknown trigger),
    # the way a plugin uninstall would have.
    v1 = await versions.get_version(db, rule.id, 1)
    v1.nodes = [{**v1.nodes[0], "params": {"event": "gone.event"}}, v1.nodes[1]]
    await db.flush()
    with pytest.raises(ConflictError):
        await automations.restore_version(db, rule.id, 1, admin.id)


async def test_version_reads_carry_the_author(db, admin):
    rule = await automations.create_rule(db, RuleCreate.model_validate(_graph("item.created", "one")), admin.id)
    reads = await automations.version_reads(db, await versions.list_versions(db, rule.id))
    assert reads[0].created_by_name == admin.name and reads[0].node_count == 2
    assert (await automations.rule_reads(db, [rule]))[0].version == 1
