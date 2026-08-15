import base64
import hashlib
import hmac
import json
import secrets as py_secrets
import time
import uuid
from datetime import timedelta

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.modules.fields import service as fields_service
from radd.modules.items.redaction import redact_item_payload
from radd.exceptions import NotFoundError
from radd.modules.events import service as events
from radd.modules.events.service import Event
from radd.clock import utcnow

from .models import WebhookDelivery, WebhookEndpoint
from .schemas import EndpointCreate, EndpointUpdate
from .types import (
    CONSUMER_NAME,
    SECRET_PREFIX,
    SIGNATURE_VERSION,
    DeliveryStatus,
    WebhookEntity,
    WebhookEvent,
)



def generate_secret() -> str:
    return SECRET_PREFIX + base64.b64encode(py_secrets.token_bytes(32)).decode()


def sign(secret: str, msg_id: str, timestamp: int, body: str) -> str:
    key = base64.b64decode(secret.removeprefix(SECRET_PREFIX))
    signed_content = f"{msg_id}.{timestamp}.{body}".encode()
    digest = hmac.new(key, signed_content, hashlib.sha256).digest()
    return f"{SIGNATURE_VERSION},{base64.b64encode(digest).decode()}"


async def create_endpoint(
    session: AsyncSession, data: EndpointCreate, actor_id: uuid.UUID | None = None
) -> WebhookEndpoint:
    endpoint = WebhookEndpoint(
        url=data.url,
        secret=generate_secret(),
        description=data.description,
        event_types=data.event_types,
    )
    session.add(endpoint)
    await session.flush()
    await events.emit(
        session,
        event_type=WebhookEvent.ENDPOINT_CREATED,
        entity_type=WebhookEntity.ENDPOINT,
        entity_id=endpoint.id,
        actor_id=actor_id,
        payload={"url": endpoint.url, "event_types": endpoint.event_types},
    )
    return endpoint


async def update_endpoint(
    session: AsyncSession,
    endpoint_id: uuid.UUID,
    data: EndpointUpdate,
    actor_id: uuid.UUID | None = None,
) -> WebhookEndpoint:
    endpoint = await get_endpoint(session, endpoint_id)
    for attr in ("url", "description", "event_types", "active"):
        value = getattr(data, attr)
        if value is not None:
            setattr(endpoint, attr, value)
    await session.flush()
    await events.emit(
        session,
        event_type=WebhookEvent.ENDPOINT_UPDATED,
        entity_type=WebhookEntity.ENDPOINT,
        entity_id=endpoint.id,
        actor_id=actor_id,
        payload={"url": endpoint.url, "active": endpoint.active},
    )
    return endpoint


async def delete_endpoint(
    session: AsyncSession, endpoint_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> None:
    """Delete an endpoint and its delivery log (spec 87 — webhook.delete had no
    endpoint). Deliveries have no CASCADE (the log outlives individual sends), so
    they are cleared explicitly; both tables belong to this module."""
    endpoint = await get_endpoint(session, endpoint_id)
    await session.execute(
        delete(WebhookDelivery).where(WebhookDelivery.endpoint_id == endpoint_id)
    )
    await events.emit(
        session,
        event_type=WebhookEvent.ENDPOINT_DELETED,
        entity_type=WebhookEntity.ENDPOINT,
        entity_id=endpoint.id,
        actor_id=actor_id,
        payload={"url": endpoint.url},
    )
    await session.delete(endpoint)
    await session.flush()


async def get_endpoint(session: AsyncSession, endpoint_id: uuid.UUID) -> WebhookEndpoint:
    endpoint = await session.get(WebhookEndpoint, endpoint_id)
    if endpoint is None:
        raise NotFoundError(WebhookEntity.ENDPOINT, endpoint_id)
    return endpoint


async def list_endpoints(session: AsyncSession) -> list[WebhookEndpoint]:
    result = await session.execute(
        select(WebhookEndpoint).order_by(WebhookEndpoint.created_at)
    )
    return list(result.scalars())


async def list_deliveries(
    session: AsyncSession, endpoint_id: uuid.UUID, limit: int
) -> list[WebhookDelivery]:
    result = await session.execute(
        select(WebhookDelivery)
        .where(WebhookDelivery.endpoint_id == endpoint_id)
        .order_by(WebhookDelivery.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars())


async def fanout_events(session: AsyncSession) -> int:
    """Advance this consumer's cursor, creating pending deliveries for matching endpoints."""
    offset = await events.get_offset(session, CONSUMER_NAME)
    batch = await events.read_after(session, offset, settings.webhook_fanout_batch)
    if not batch:
        return 0
    result = await session.execute(
        select(WebhookEndpoint).where(WebhookEndpoint.active.is_(True))
    )
    endpoints = list(result.scalars())
    now = utcnow()
    for event in batch:
        if event.silent:  # a bulk import must not fan 45k deliveries at subscribers
            continue
        for endpoint in endpoints:
            if endpoint.event_types and event.event_type not in endpoint.event_types:
                continue
            session.add(
                WebhookDelivery(
                    endpoint_id=endpoint.id,
                    event_id=event.id,
                    status=DeliveryStatus.PENDING.value,
                    next_attempt_at=now,
                )
            )
    await events.set_offset(session, CONSUMER_NAME, batch[-1].id)
    return len(batch)


async def attempt_due(session: AsyncSession, client: httpx.AsyncClient) -> int:
    now = utcnow()
    # RADD-1085: resolved once per batch — an endpoint can hold no grant and
    # sit in no team, so anything read-restricted for anybody is restricted
    # for every delivery in this batch.
    restricted = await fields_service.outbound_restricted_keys(session)
    result = await session.execute(
        select(WebhookDelivery)
        .where(
            WebhookDelivery.status == DeliveryStatus.PENDING.value,
            WebhookDelivery.next_attempt_at <= now,
        )
        .order_by(WebhookDelivery.next_attempt_at)
        .limit(settings.webhook_attempt_batch)
    )
    deliveries = list(result.scalars())
    for delivery in deliveries:
        await _attempt(session, client, delivery, restricted)
    return len(deliveries)


async def _attempt(
    session: AsyncSession,
    client: httpx.AsyncClient,
    delivery: WebhookDelivery,
    restricted: tuple[frozenset[str], frozenset[str]],
) -> None:
    endpoint = await session.get(WebhookEndpoint, delivery.endpoint_id)
    event = await events.get_event(session, delivery.event_id)
    if endpoint is None or event is None or not endpoint.active:
        delivery.status = DeliveryStatus.DEAD.value
        delivery.last_error = "endpoint or event vanished, or endpoint disabled"
        return
    msg_id = f"msg_{delivery.id}"
    timestamp = int(time.time())
    body = _payload_body(msg_id, event, restricted)
    headers = {
        "content-type": "application/json",
        "webhook-id": msg_id,
        "webhook-timestamp": str(timestamp),
        "webhook-signature": sign(endpoint.secret, msg_id, timestamp, body),
    }
    try:
        response = await client.post(endpoint.url, content=body, headers=headers)
        delivery.last_status_code = response.status_code
        if 200 <= response.status_code < 300:
            delivery.status = DeliveryStatus.SUCCESS.value
            delivery.last_error = None
            return
        _schedule_retry(delivery, error=f"HTTP {response.status_code}")
    except httpx.HTTPError as exc:
        delivery.last_status_code = None
        _schedule_retry(delivery, error=str(exc)[:500])


def _payload_body(
    msg_id: str, event: Event, restricted: tuple[frozenset[str], frozenset[str]]
) -> str:
    return json.dumps(
        {
            "id": msg_id,
            "type": event.event_type,
            "timestamp": event.created_at.isoformat(),
            "data": _outbound_payload(event.payload, restricted),
        },
        separators=(",", ":"),
    )


def _outbound_payload(
    payload: dict | None, restricted: tuple[frozenset[str], frozenset[str]]
) -> dict:
    """What actually leaves the building (RADD-1085): restricted custom fields
    and builtins redacted from item payloads, and internal-comment excerpts
    withheld — an endpoint is not on any team, so team-gated text is not its
    to read. Copy-on-write throughout: `payload` is the events row's JSONB."""
    custom_keys, builtin_names = restricted
    data = redact_item_payload(payload, custom_keys, builtin_names)
    if data.get("visibility") == "internal" and data.get("excerpt"):
        if data is payload:
            data = dict(payload)
        data["excerpt"] = None
    return data


def _schedule_retry(delivery: WebhookDelivery, error: str) -> None:
    delivery.attempts += 1
    delivery.last_error = error
    schedule = settings.webhook_retry_schedule
    if delivery.attempts > len(schedule):
        delivery.status = DeliveryStatus.DEAD.value
    else:
        delivery.next_attempt_at = utcnow() + timedelta(seconds=schedule[delivery.attempts - 1])
