import uuid
from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import Text, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import ilike_term

# `Event` is re-exported here as the PUBLIC consumer payload type (RADD-886):
# the row IS the contract every consumer loop receives, and importing it from
# events.models made 13 modules reach into another module's models file. The
# ratchet test bans `events.models` outside this module.
from .models import ConsumerOffset, Event
from .quiet import automated, is_automated, is_quiet, quiet

__all__ = ["Event", "quiet", "is_quiet", "automated", "is_automated"]  # re-exported public seam (see above)


async def emit(
    session: AsyncSession,
    *,
    event_type: StrEnum,
    entity_type: StrEnum,
    entity_id: object,
    actor_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
    subjects: dict[str, Any] | None = None,
    occurred_at: datetime | None = None,
    silent: bool | None = None,
    automated_cause: bool | None = None,
) -> None:
    """Append to the outbox inside the caller's transaction — commits or rolls back with it.

    `occurred_at` overrides the row's timestamp for historical imports (naive UTC);
    the monotonic `id` still orders the stream, so consumers are unaffected.

    `silent` defaults to whether the caller is inside an `events.quiet()` scope, so
    a bulk import marks its whole event stream without any service in the call
    chain having to know an import is running. Pass it explicitly to override.

    **`subjects` are IDS; the kernel writes the shape (RADD-923.)** Pass
    `subjects={"item": item_id}` and `payload["item"]` becomes the canonical ref
    for that entity, resolved through `registries.entity_refs`. Emitters do not
    build refs, so they cannot build them differently — which is what fourteen
    of them had done before RADD-922 fixed it by hand.
    """
    payload = await _with_subjects(session, payload, subjects)
    event = Event(
        event_type=str(event_type),
        entity_type=str(entity_type),
        entity_id=str(entity_id),
        actor_id=actor_id,
        payload=payload or {},
        silent=is_quiet() if silent is None else silent,
        automated=is_automated() if automated_cause is None else automated_cause,
    )
    if occurred_at is not None:
        event.created_at = occurred_at.replace(tzinfo=None)
    session.add(event)


async def _with_subjects(
    session: AsyncSession,
    payload: dict[str, Any] | None,
    subjects: dict[str, Any] | None,
) -> dict[str, Any]:
    """Expand `{entity_type: id}` into canonical refs on the payload (RADD-923).

    The kernel registry is the only thing this module reaches for — `events` still
    depends on no plugin, which is the property that lets it load first.

    An entity type with no registered ref is a PROGRAMMING error, and the loader
    already refuses to boot a plugin whose declared subjects are unresolvable.
    Reaching here means an undeclared subject was passed at a call site, so it
    raises in debug and degrades to a bare id in production — a slightly thin
    payload is a better outcome than a failed user write, because the event is a
    side effect of somebody else's action.
    """
    from radd.kernel.registry import registries

    result = dict(payload or {})
    for entity_type, entity_id in (subjects or {}).items():
        if entity_id is None:
            result[entity_type] = None
            continue
        spec = registries.entity_refs.get(entity_type)
        if spec is None:
            if settings.debug:
                raise RuntimeError(
                    f"event subject {entity_type!r} has no registered EntityRefSpec — "
                    f"declare one on the plugin that owns the entity"
                )
            result[entity_type] = {"id": str(entity_id)}
            continue
        if entity_type in result:
            # The plugin's own data would be overwritten by the ref, or vice
            # versa. Either way somebody is about to read the wrong thing, so it
            # fails where it can still be fixed rather than silently resolving.
            raise RuntimeError(
                f"event payload already has {entity_type!r}; it collides with the "
                f"subject ref of the same name — rename the payload key"
            )
        result[entity_type] = await spec.ref(session, entity_id)
    return result


async def read_after(session: AsyncSession, after: int, limit: int) -> list[Event]:
    result = await session.execute(
        select(Event).where(Event.id > after).order_by(Event.id).limit(limit)
    )
    return list(result.scalars())


async def query_events(
    session: AsyncSession,
    *,
    entity_type: str | None = None,
    entity_id: str | None = None,
    event_types: Sequence[str] | None = None,
    actor_id: uuid.UUID | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    q: str | None = None,
    ascending: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[Event]:
    """Filtered read of the audit log — the query behind the admin audit view.

    Any combination of filters ANDs together; results are the newest first by
    default (id DESC). The events table is append-only, so this IS the audit trail.

    `q` (RADD-884) matches the event type or anywhere in the payload text.
    Newest-first with a LIMIT, Postgres stops as soon as the page fills — fast
    for anything that occurs, a tail scan only for terms that never match,
    which an admin page wears.
    """
    conditions = []
    if q:
        pattern = ilike_term(q)
        conditions.append(
            Event.event_type.ilike(pattern) | func.cast(Event.payload, Text).ilike(pattern)
        )
    if entity_type is not None:
        conditions.append(Event.entity_type == entity_type)
    if entity_id is not None:
        conditions.append(Event.entity_id == entity_id)
    if event_types:
        conditions.append(Event.event_type.in_(list(event_types)))
    if actor_id is not None:
        conditions.append(Event.actor_id == actor_id)
    if start is not None:
        conditions.append(Event.created_at >= start)
    if end is not None:
        conditions.append(Event.created_at <= end)
    order = Event.id.asc() if ascending else Event.id.desc()
    result = await session.execute(
        select(Event).where(*conditions).order_by(order).limit(limit).offset(offset)
    )
    return list(result.scalars())


async def entity_activity(
    session: AsyncSession,
    *,
    entity_type: str,
    entity_id: object,
    related_event_types: Sequence[str] = (),
    limit: int = 500,
) -> list[Event]:
    """The full chronological activity feed for one entity: events emitted directly
    on it (`entity_type`/`entity_id`) UNION events of `related_event_types` whose
    payload `item.id` points back at it (comments, worklogs, links attached to it).
    Ordered oldest→newest. `entity_type` is a parameter so events stays domain-agnostic.
    """
    key = str(entity_id)
    direct = and_(Event.entity_type == entity_type, Event.entity_id == key)
    clauses = [direct]
    if related_event_types:
        clauses.append(
            and_(
                Event.event_type.in_(list(related_event_types)),
                # RADD-922: the canonical ref, not the old bare `item_id`.
                Event.payload["item"]["id"].astext == key,
            )
        )
    result = await session.execute(
        select(Event).where(or_(*clauses)).order_by(Event.id).limit(limit)
    )
    return list(result.scalars())


async def get_event(session: AsyncSession, event_id: int) -> Event | None:
    return await session.get(Event, event_id)


async def latest_event_id(session: AsyncSession) -> int:
    """The stream head — where an ephemeral tail (realtime) starts. 0 on empty."""
    result = await session.execute(select(func.max(Event.id)))
    return result.scalar() or 0


async def get_offset(session: AsyncSession, consumer: str) -> int:
    row = await session.get(ConsumerOffset, consumer)
    return row.last_event_id if row else 0


async def offset_exists(session: AsyncSession, consumer: str) -> bool:
    """False only before a consumer's very first cursor write — lets a new consumer
    distinguish 'never ran' (bootstrap over the backlog) from 'caught up at 0'."""
    return await session.get(ConsumerOffset, consumer) is not None


async def set_offset(session: AsyncSession, consumer: str, event_id: int) -> None:
    row = await session.get(ConsumerOffset, consumer)
    if row is None:
        session.add(ConsumerOffset(name=consumer, last_event_id=event_id))
    else:
        row.last_event_id = event_id


async def consumer_status(session: AsyncSession) -> list[dict[str, Any]]:
    """Every consumer's cursor vs the stream head, for monitoring: name, lag,
    and seconds since the cursor last moved (computed server-side against the
    same clock that wrote `updated_at`, so timezones can't skew it)."""
    head = await latest_event_id(session)
    result = await session.execute(
        select(
            ConsumerOffset.name,
            ConsumerOffset.last_event_id,
            func.extract("epoch", func.now() - ConsumerOffset.updated_at),
        ).order_by(ConsumerOffset.name)
    )
    return [
        {
            "name": name,
            "last_event_id": last_event_id,
            "stream_head": head,
            "lag": max(0, head - last_event_id),
            "seconds_since_update": max(0, int(seconds or 0)),
        }
        for name, last_event_id, seconds in result.all()
    ]
