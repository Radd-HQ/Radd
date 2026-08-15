"""RADD-1096 — a dead delivery replays with a fresh retry schedule."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import ConflictError, NotFoundError
from radd.modules.events.models import Event
from radd.modules.webhooks import service as webhooks
from radd.modules.webhooks.models import WebhookDelivery, WebhookEndpoint
from radd.modules.webhooks.types import DeliveryStatus


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _endpoint_with(db, status: str) -> tuple[WebhookEndpoint, WebhookDelivery]:
    event = Event(
        event_type="item.updated", entity_type="item", entity_id=str(uuid.uuid4()),
        payload={},
    )
    db.add(event)
    await db.flush()
    endpoint = WebhookEndpoint(
        id=uuid.uuid4(), url="https://receiver.example/hook",
        secret="whsec_test", description="", event_types=None, active=True,
    )
    db.add(endpoint)
    await db.flush()
    delivery = WebhookDelivery(
        id=uuid.uuid4(), endpoint_id=endpoint.id, event_id=event.id,
        status=status, attempts=6, last_error="HTTP 503",
        next_attempt_at=webhooks.utcnow(),
    )
    db.add(delivery)
    await db.flush()
    return endpoint, delivery


async def test_dead_delivery_replays_fresh(db):
    endpoint, delivery = await _endpoint_with(db, DeliveryStatus.DEAD.value)
    replayed = await webhooks.replay_delivery(db, endpoint.id, delivery.id)
    assert replayed.status == DeliveryStatus.PENDING.value
    assert replayed.attempts == 0
    assert replayed.last_error is None


async def test_only_dead_deliveries_replay(db):
    endpoint, delivery = await _endpoint_with(db, DeliveryStatus.SUCCESS.value)
    with pytest.raises(ConflictError):
        await webhooks.replay_delivery(db, endpoint.id, delivery.id)


async def test_replay_refuses_a_foreign_endpoint(db):
    _, delivery = await _endpoint_with(db, DeliveryStatus.DEAD.value)
    with pytest.raises(NotFoundError):
        await webhooks.replay_delivery(db, uuid.uuid4(), delivery.id)
