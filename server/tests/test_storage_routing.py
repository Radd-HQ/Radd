"""Storage routing chain (spec 102): first match wins, everything falls through
toward the default, and a rule can only pick a REAL host — never error an
upload out. The LLM rule is exercised with a stubbed AI client (choice, timeout,
refusal); CIDR matching is pure.
"""

import asyncio
import io
import uuid

import pytest
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.modules.attachments import hosts, service
from radd.modules.attachments.routing import engine, rules, store
from radd.modules.attachments.routing.context import RoutingContext
from radd.modules.attachments.schemas import StorageHostCreate
from radd.modules.attachments.types import (
    AttachmentParentType,
    DeliveryMode,
    RuleType,
    StorageHostType,
)
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole


@pytest.fixture
async def db():
    engine_ = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine_, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine_.dispose()


async def _host(db, tmp_path, name: str, *, default: bool = False, selectable: bool = False):
    return await hosts.create_host(
        db,
        StorageHostCreate(
            name=f"{name}-{uuid.uuid4().hex[:6]}",
            host_type=StorageHostType.FILESYSTEM,
            root_dir=str(tmp_path / name),
            delivery_mode=DeliveryMode.PROXY,
            is_default=default,
            user_selectable=selectable,
        ),
    )


def _ctx(**overrides) -> RoutingContext:
    values = dict(
        actor_id=uuid.uuid4(),
        source_ip=None,
        chosen_host_id=None,
        filename="f.png",
        content_type="image/png",
        size_bytes=3,
        entity_type=AttachmentParentType.ITEM.value,
        entity_id=uuid.uuid4(),
        project_id=None,
        content=lambda: b"png",
    )
    values.update(overrides)
    return RoutingContext(**values)


async def test_empty_chain_routes_to_the_default_host(db, tmp_path):
    default = await _host(db, tmp_path, "default", default=True)
    decided = await engine.decide(db, _ctx())
    assert decided.id == default.id


async def test_first_match_wins_and_disabled_rules_are_skipped(db, tmp_path):
    default = await _host(db, tmp_path, "default", default=True)
    zone_a = await _host(db, tmp_path, "zone-a")
    zone_b = await _host(db, tmp_path, "zone-b")
    first = await store.create_rule(
        db,
        name="zone A",
        rule_type=RuleType.CIDR,
        config={"ranges": [{"cidr": "10.0.0.0/8", "host_id": str(zone_a.id)}]},
    )
    await store.create_rule(
        db,
        name="zone B (also matches, later)",
        rule_type=RuleType.CIDR,
        config={"ranges": [{"cidr": "10.0.0.0/8", "host_id": str(zone_b.id)}]},
    )
    decided = await engine.decide(db, _ctx(source_ip="10.1.2.3"))
    assert decided.id == zone_a.id
    # Disable the first -> the second takes over; no IP at all -> default.
    await store.update_rule(db, first.id, enabled=False)
    assert (await engine.decide(db, _ctx(source_ip="10.1.2.3"))).id == zone_b.id
    assert (await engine.decide(db, _ctx(source_ip=None))).id == default.id


async def test_user_choice_honors_only_selectable_hosts(db, tmp_path):
    default = await _host(db, tmp_path, "default", default=True)
    offered = await _host(db, tmp_path, "offered", selectable=True)
    private = await _host(db, tmp_path, "private")  # not selectable
    await store.create_rule(db, name="ask", rule_type=RuleType.USER_CHOICE, config={})
    chosen = await engine.decide(db, _ctx(chosen_host_id=offered.id))
    assert chosen.id == offered.id
    # A forged/stale choice of a non-selectable host falls through to default.
    assert (await engine.decide(db, _ctx(chosen_host_id=private.id))).id == default.id
    # No choice sent (API/importer uploads) -> straight through.
    assert (await engine.decide(db, _ctx())).id == default.id


async def test_llm_rule_maps_answers_and_falls_through_on_failure(db, tmp_path, monkeypatch):
    default = await _host(db, tmp_path, "default", default=True)
    content_host = await _host(db, tmp_path, "content")
    await store.create_rule(
        db,
        name="classify images",
        rule_type=RuleType.LLM,
        config={
            "prompt": "human characters or 3d assets -> content",
            "answers": [
                {"answer": "content", "host_id": str(content_host.id)},
                {"answer": "general", "host_id": str(default.id)},
            ],
            "timeout_seconds": 5,
        },
    )
    from radd.modules.ai import client as ai_client
    from radd.modules.ai import features as ai_features

    async def feature_on(session, feature):
        return True

    monkeypatch.setattr(ai_features, "feature_enabled", feature_on)

    async def classify(session, role, *, prompt, choices, image_bytes=None, image_media_type=None):
        assert image_bytes == b"png"
        return "content"

    monkeypatch.setattr(ai_client, "complete_choice", classify)
    assert (await engine.decide(db, _ctx())).id == content_host.id

    # Non-image content types are not the rule's business.
    assert (
        await engine.decide(db, _ctx(content_type="application/pdf"))
    ).id == default.id

    # Upstream failure -> fall through, never an error.
    async def broken(session, role, **kwargs):
        from radd.modules.ai.types import AiUpstreamError

        raise AiUpstreamError("provider down")

    monkeypatch.setattr(ai_client, "complete_choice", broken)
    assert (await engine.decide(db, _ctx())).id == default.id

    # Timeout -> fall through.
    async def hangs(session, role, **kwargs):
        await asyncio.sleep(30)

    monkeypatch.setattr(ai_client, "complete_choice", hangs)
    await store.update_rule(
        db,
        (await store.ordered_rules(db))[0].id,
        config={
            "prompt": "p",
            "answers": [
                {"answer": "content", "host_id": str(content_host.id)},
                {"answer": "general", "host_id": str(default.id)},
            ],
            "timeout_seconds": 1,
        },
    )
    assert (await engine.decide(db, _ctx())).id == default.id


async def test_rule_naming_a_vanished_host_is_skipped(db, tmp_path):
    default = await _host(db, tmp_path, "default", default=True)
    ghost = uuid.uuid4()
    rule = await store.create_rule(
        db,
        name="ghost",
        rule_type=RuleType.CIDR,
        config={"ranges": [{"cidr": "0.0.0.0/0", "host_id": str(ghost)}]},
    )
    assert (await engine.decide(db, _ctx(source_ip="1.2.3.4"))).id == default.id
    _ = rule


async def test_rule_config_is_validated_on_write():
    with pytest.raises(store.RuleConfigError):
        store.validate_config(RuleType.CIDR.value, {"ranges": []})
    with pytest.raises(store.RuleConfigError):
        store.validate_config(RuleType.LLM.value, {"prompt": "p", "answers": [{"answer": "only-one", "host_id": str(uuid.uuid4())}]})
    with pytest.raises(store.RuleConfigError):
        store.validate_config("no_such_type", {})
    validated = store.validate_config(
        RuleType.CIDR.value,
        {"ranges": [{"cidr": "10.0.0.0/8", "host_id": str(uuid.uuid4())}]},
    )
    assert validated["ranges"][0]["cidr"] == "10.0.0.0/8"


async def test_choice_reachability_ask_only_when_the_answer_matters(
    db, tmp_path, monkeypatch
):
    """Spec 102 follow-up: prompting and then discarding the answer is broken —
    the ask is suppressed exactly when an earlier rule would capture the files."""
    default = await _host(db, tmp_path, "default", default=True)
    content_host = await _host(db, tmp_path, "content", selectable=True)
    llm = await store.create_rule(
        db,
        name="Classify images",
        rule_type=RuleType.LLM,
        config={
            "prompt": "p",
            "answers": [
                {"answer": "content", "host_id": str(content_host.id)},
                {"answer": "general", "host_id": str(default.id)},
            ],
        },
    )
    ask = await store.create_rule(db, name="Ask", rule_type=RuleType.USER_CHOICE, config={})

    async def llm_live(session):
        return True

    monkeypatch.setattr(engine, "_llm_live", llm_live)

    # Images are captured by the LLM rule sitting first -> no prompt, named why.
    reachable, preempted = await engine.choice_reachable(
        db, source_ip=None, content_types=["image/png"]
    )
    assert reachable is False and preempted == "Classify images"
    # A PDF falls through the LLM rule -> the choice matters -> ask.
    reachable, _ = await engine.choice_reachable(
        db, source_ip=None, content_types=["application/pdf"]
    )
    assert reachable is True
    # Mixed gesture: any file reaching the ask means asking.
    reachable, _ = await engine.choice_reachable(
        db, source_ip=None, content_types=["image/png", "application/pdf"]
    )
    assert reachable is True
    # LLM feature dormant -> images fall through too -> ask.
    async def llm_dead(session):
        return False

    monkeypatch.setattr(engine, "_llm_live", llm_dead)
    reachable, _ = await engine.choice_reachable(db, source_ip=None, content_types=["image/png"])
    assert reachable is True
    monkeypatch.setattr(engine, "_llm_live", llm_live)

    # Reorder: ask first -> the choice always matters, images included.
    await store.reorder(db, [ask.id, llm.id])
    reachable, _ = await engine.choice_reachable(db, source_ip=None, content_types=["image/png"])
    assert reachable is True

    # A CIDR rule matching the caller's network captures EVERYTHING ahead of the ask.
    await store.reorder(db, [llm.id, ask.id])
    zone = await store.create_rule(
        db,
        name="Zone net",
        rule_type=RuleType.CIDR,
        config={"ranges": [{"cidr": "172.16.0.0/12", "host_id": str(content_host.id)}]},
    )
    await store.reorder(db, [zone.id, llm.id, ask.id])
    reachable, preempted = await engine.choice_reachable(
        db, source_ip="172.16.9.9", content_types=["application/pdf"]
    )
    assert reachable is False and preempted == "Zone net"
    reachable, _ = await engine.choice_reachable(
        db, source_ip="10.0.0.1", content_types=["application/pdf"]
    )
    assert reachable is True


async def test_choice_unreachable_without_any_ask_rule(db, tmp_path):
    await _host(db, tmp_path, "default", default=True)
    reachable, preempted = await engine.choice_reachable(
        db, source_ip=None, content_types=["image/png"]
    )
    assert (reachable, preempted) == (False, None)


def test_cidr_matching_is_pure_and_tolerant():
    host_id = uuid.uuid4()
    ranges = [rules.CidrRange(cidr="10.0.0.0/8", host_id=host_id)]
    assert rules.match_cidr("10.9.9.9", ranges) == host_id
    assert rules.match_cidr("192.168.1.1", ranges) is None
    assert rules.match_cidr("garbage", ranges) is None
    assert rules.match_cidr(None, ranges) is None


async def test_routed_save_upload_lands_on_the_decided_host(db, tmp_path):
    """End to end through service.save_upload: a CIDR rule routes the bytes."""
    from radd.modules.items import service as items_service
    from radd.modules.items.schemas import ItemCreate
    from radd.modules.projects import service as projects_service
    from radd.modules.projects.schemas import ProjectCreate
    from pathlib import Path

    admin = User(
        email=f"route-{uuid.uuid4().hex[:8]}@example.com",
        name="Router",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(admin)
    await db.flush()
    await _host(db, tmp_path, "default", default=True)
    zoned = await _host(db, tmp_path, "zoned")
    await store.create_rule(
        db,
        name="zone",
        rule_type=RuleType.CIDR,
        config={"ranges": [{"cidr": "172.16.0.0/12", "host_id": str(zoned.id)}]},
    )
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"RT{uuid.uuid4().hex[:4].upper()}", name="Route P")
    )
    item = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="routed"), actor=admin
    )
    attachment = await service.save_upload(
        db,
        entity_type=AttachmentParentType.ITEM.value,
        entity_id=item.id,
        upload=UploadFile(file=io.BytesIO(b"zone-bytes"), filename="z.png", headers=None),
        actor_id=admin.id,
        source_ip="172.16.5.5",
    )
    assert attachment.storage_host_id == zoned.id
    assert (Path(zoned.root_dir) / attachment.storage_name).read_bytes() == b"zone-bytes"
