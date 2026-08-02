"""Quiet events (spec 100) — `events.quiet()` marks a scope's events `silent`, and
the consumers that reach OUTSIDE the instance skip them.

This is the invariant a bulk import depends on: 45k imported issues must not send
45k notifications, fire 45k webhook deliveries or trigger the automation rules of
a workflow the work never actually went through. Equally load-bearing is the
asymmetry — the search index and the activity feed DO consume silent events,
because an imported issue must be findable and must have history.

The wedge case is called out explicitly: consumers skip silent events inside their
loop and still advance the cursor past them. Filtering them out in SQL instead
would leave a batch of nothing but silent events looking like an empty stream, and
the cursor would never move past them.

DB-backed tests are flushed, never committed; the session rolls back at teardown.
"""

import asyncio
import uuid
from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.automations.engine import should_process
from radd.modules.events import service as events
from radd.modules.events.models import Event
from radd.modules.items import service as items
from radd.modules.items.enums import ItemEntity, ItemEvent
from radd.modules.items.schemas import ItemCreate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.search import indexer
from radd.modules.search.models import SearchIndexRow
from radd.modules.webhooks import service as webhooks
from radd.modules.webhooks.models import WebhookDelivery, WebhookEndpoint
from radd.modules.webhooks.types import CONSUMER_NAME as WEBHOOK_CONSUMER


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def actor(db) -> User:
    user = User(
        email=f"quiet-{uuid.uuid4().hex[:8]}@example.com",
        name="Quiet Tester",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _emit(db, *, silent_scope: bool) -> Event:
    with events.quiet(silent_scope):
        await events.emit(
            db,
            event_type=ItemEvent.CREATED,
            entity_type=ItemEntity.ITEM,
            entity_id=uuid.uuid4(),
        )
    await db.flush()
    result = await db.execute(select(Event).order_by(Event.id.desc()).limit(1))
    return result.scalar_one()


# --- the scope itself (pure) --------------------------------------------------


def test_quiet_sets_and_restores():
    assert events.is_quiet() is False
    with events.quiet():
        assert events.is_quiet() is True
    assert events.is_quiet() is False


def test_quiet_disabled_is_a_no_op():
    # So a caller can pass a user-facing toggle straight through without branching.
    with events.quiet(False):
        assert events.is_quiet() is False


def test_quiet_restores_the_outer_value_when_nested():
    with events.quiet():
        with events.quiet(False):
            assert events.is_quiet() is False
        assert events.is_quiet() is True


def test_quiet_restores_on_exception():
    with pytest.raises(RuntimeError):
        with events.quiet():
            raise RuntimeError("boom")
    assert events.is_quiet() is False


async def test_quiet_is_inherited_by_a_task_created_inside_the_scope():
    """The whole design rests on this: an import run is one background task, and a
    single `with` around its body has to cover every service it calls."""
    inside: list[bool] = []
    outside: list[bool] = []

    async def probe(sink: list[bool]) -> None:
        await asyncio.sleep(0)
        sink.append(events.is_quiet())

    with events.quiet():
        await asyncio.create_task(probe(inside))
    await asyncio.create_task(probe(outside))

    assert inside == [True]
    assert outside == [False]  # a task started after the scope is unaffected


# --- emit stamps the column ---------------------------------------------------


async def test_emit_marks_events_silent_inside_the_scope(db):
    assert (await _emit(db, silent_scope=True)).silent is True


async def test_emit_leaves_events_loud_outside_the_scope(db):
    assert (await _emit(db, silent_scope=False)).silent is False


async def test_explicit_silent_overrides_the_scope(db):
    with events.quiet():
        await events.emit(
            db,
            event_type=ItemEvent.CREATED,
            entity_type=ItemEntity.ITEM,
            entity_id=uuid.uuid4(),
            silent=False,
        )
    await db.flush()
    result = await db.execute(select(Event).order_by(Event.id.desc()).limit(1))
    assert result.scalar_one().silent is False


async def test_a_real_item_created_in_the_scope_emits_silently(db, actor):
    """The end-to-end point of a ContextVar: `items.create_item` emits the event
    several layers down and stays completely ignorant that an import is running."""
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"QT{uuid.uuid4().hex[:4].upper()}", name="Quiet")
    )
    with events.quiet():
        item = await items.create_item(
            db, ItemCreate(project_id=project.id, title="imported"), actor
        )
    await db.flush()
    result = await db.execute(
        select(Event).where(
            Event.entity_id == str(item.id), Event.event_type == ItemEvent.CREATED.value
        )
    )
    assert result.scalar_one().silent is True


# --- consumers that reach outside the instance --------------------------------


def test_automations_never_process_a_silent_event():
    """A rule that assigns on create or transitions on a field change would fire
    once per imported issue and rewrite the history being imported."""
    event = Event(
        event_type=ItemEvent.CREATED.value,
        entity_type=ItemEntity.ITEM.value,
        entity_id=str(uuid.uuid4()),
        payload={},
    )
    event.silent = False
    assert should_process(event) is True
    event.silent = True
    assert should_process(event) is False


async def test_webhook_fanout_skips_silent_events_but_still_advances_the_cursor(db):
    """The wedge case. If silent events were filtered in SQL, a batch containing
    only silent rows would read as an empty stream and the cursor would never move
    past them — the consumer would rescan the same range forever."""
    head = await events.latest_event_id(db)
    await events.set_offset(db, WEBHOOK_CONSUMER, head)
    endpoint = WebhookEndpoint(
        url="https://example.invalid/hook",
        secret="whsec_test",
        event_types=None,  # subscribed to everything
        active=True,
    )
    db.add(endpoint)

    silent_event = await _emit(db, silent_scope=True)
    loud_event = await _emit(db, silent_scope=False)

    consumed = await webhooks.fanout_events(db)
    await db.flush()

    assert consumed == 2  # both were read...
    result = await db.execute(
        select(WebhookDelivery).where(WebhookDelivery.endpoint_id == endpoint.id)
    )
    delivered = [d.event_id for d in result.scalars()]
    assert delivered == [loud_event.id]  # ...only the loud one is delivered
    # and the cursor is past the silent one, so it is never rescanned.
    assert await events.get_offset(db, WEBHOOK_CONSUMER) == loud_event.id
    assert await events.get_offset(db, WEBHOOK_CONSUMER) > silent_event.id


# --- consumers that build internal state (the deliberate asymmetry) -----------


async def test_the_search_indexer_still_indexes_a_silent_item(db, actor):
    """An imported issue must be findable. `silent` means "tell nobody", not
    "pretend this does not exist"."""
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"QS{uuid.uuid4().hex[:4].upper()}", name="Quiet Search")
    )
    with events.quiet():
        item = await items.create_item(
            db, ItemCreate(project_id=project.id, title="findable import"), actor
        )
    await db.flush()
    result = await db.execute(
        select(Event).where(
            Event.entity_id == str(item.id), Event.event_type == ItemEvent.CREATED.value
        )
    )
    event = result.scalar_one()
    assert event.silent is True

    await indexer._handle(db, event)
    await db.flush()

    row = await db.get(SearchIndexRow, item.id)
    assert row is not None
    assert row.title == "findable import"


async def test_silent_events_stay_in_the_audit_trail(db):
    """The history tab and the admin audit view read the events table directly —
    an imported issue's activity must be visible, so nothing filters them out."""
    event = await _emit(db, silent_scope=True)
    found = await events.query_events(
        db, entity_type=ItemEntity.ITEM.value, entity_id=event.entity_id
    )
    assert [e.id for e in found] == [event.id]
    assert isinstance(event.created_at, datetime)
