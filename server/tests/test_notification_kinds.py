"""RADD-1326: a plugin's event reaches the inbox and the preferences matrix with
no edit to notify.

The consumer used to answer a hardcoded set of core event types, and a kind was
a closed `NotificationType` — so a plugin's "deploy finished" could produce
neither an inbox row nor a row in anyone's settings. Here a stand-in plugin
registers one `NotificationKindSpec` (and nothing else) and its event does both,
through the same channel matrix and read check every core kind goes through.
"""

import uuid
from enum import StrEnum

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.kernel import NotificationKindSpec, load_plugins
from radd.kernel.registry import registries
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.events import service as events
from radd.modules.events.models import Event
from radd.modules.items import service as items_service
from radd.modules.items.schemas import ItemCreate
import importlib

from radd.modules.notify import consumer, lines, prefs, service as notify_service
from radd.modules.notify.models import Notification
from radd.modules.notify.schemas import NotificationPrefsUpdate, NotificationRuleWrite
from radd.modules.notify.types import Channel, RuleScope
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate

KIND = "acme.deploy"
#: The package exports its APIRouter as `router`, shadowing the module.
notify_router = importlib.import_module("radd.modules.notify.router")


class AcmeEvent(StrEnum):
    DEPLOYED = "acme.deployed"


class AcmeEntity(StrEnum):
    DEPLOY = "acme_deploy"


@pytest.fixture
async def db():
    load_plugins(settings.modules)
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def people(db):
    def person(name: str) -> User:
        return User(email=f"{name}-{uuid.uuid4().hex[:8]}@example.com", name=name, instance_role=InstanceRole.ADMIN.value)

    deployer, oncall = person("deployer"), person("oncall")
    db.add_all([deployer, oncall])
    await db.flush()
    return deployer, oncall


@pytest.fixture
def acme_kind(people):
    """The whole of the plugin's notify contribution: one spec."""
    _deployer, oncall = people

    async def recipients(session, event):
        return [oncall.id, event.actor_id]  # the actor is dropped by notify

    def render(payload, actor_name):
        return {"headline": f"{actor_name} deployed to {payload['env']}", "link": "/deploys/42"}

    spec = NotificationKindSpec(
        key=KIND, label="Deploys", description="A deploy finished.",
        personal=True, default_channel="inbox",
        events=(AcmeEvent.DEPLOYED.value,), recipients=recipients, render=render,
    )
    registries.notification_kinds[KIND] = spec
    yield spec
    registries.notification_kinds.pop(KIND, None)


async def _deploy(db, actor: User, **extra) -> Event:
    await events.emit(
        db, event_type=AcmeEvent.DEPLOYED, entity_type=AcmeEntity.DEPLOY, entity_id=uuid.uuid4(),
        actor_id=actor.id, payload={"env": "production"}, **extra,
    )
    await db.flush()
    return (await db.execute(select(Event).where(Event.event_type == KIND.replace("deploy", "deployed")).order_by(Event.id.desc()).limit(1))).scalar_one()


async def _rows(db, user: User) -> list[Notification]:
    return list((await db.execute(select(Notification).where(Notification.user_id == user.id))).scalars())


async def test_a_plugins_event_becomes_an_inbox_row(db, people, acme_kind):
    deployer, oncall = people
    event = await _deploy(db, deployer)
    await consumer._handle(db, event, watch_only=False)

    [row] = await _rows(db, oncall)
    assert row.type == KIND and row.inbox is True
    assert await _rows(db, deployer) == [], "the actor is never told about their own action"
    read = notify_router._to_read(row)
    assert read.type == KIND and read.detail["headline"] == f"{deployer.name} deployed to production"
    entry = lines.entry(row, {deployer.id: deployer.name})
    assert entry.headline == read.detail["headline"] and entry.url.endswith("/deploys/42")
    # The inbox list itself carries it.
    assert [n.id for n in await notify_service.list_notifications(db, oncall.id)] == [row.id]


async def test_a_plugins_kind_is_a_row_in_the_matrix_and_can_be_turned_off(db, people, acme_kind):
    deployer, oncall = people
    read = await prefs.read(db, oncall)
    assert KIND in [k.kind for k in read.kinds]
    assert read.defaults[RuleScope.OWN][KIND] is Channel.INBOX

    # The person switches it off through the ordinary preferences PUT.
    await notify_router.put_preferences(
        NotificationPrefsUpdate(
            rules=[NotificationRuleWrite(scope=RuleScope.OWN, channels={KIND: Channel.OFF})], email_digest=True
        ),
        db, oncall,
    )
    await consumer._handle(db, await _deploy(db, deployer), watch_only=False)
    assert await _rows(db, oncall) == []


async def test_an_item_scoped_plugin_kind_passes_the_same_read_check(db, people, acme_kind):
    """With an issue as subject, the row carries it — through `_allowed`, the
    per-row read gate every core kind uses."""
    deployer, oncall = people
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"NK{uuid.uuid4().hex[:4].upper()}", name="Kinds")
    )
    item = await items_service.create_item(db, ItemCreate(project_id=project.id, title="ship"), deployer)
    await consumer._handle(db, await _deploy(db, deployer, subjects={"item": item.id}), watch_only=False)
    [row] = await _rows(db, oncall)
    assert row.item_id == item.id and row.type == KIND


def test_an_unknown_kind_is_still_refused_by_the_preferences_api():
    with pytest.raises(ValueError, match="unknown notification kind"):
        NotificationRuleWrite(scope=RuleScope.OWN, channels={"nobody.registered.this": Channel.OFF})
