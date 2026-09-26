import uuid
from contextlib import contextmanager
from collections.abc import Iterable, Sequence
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import ilike_term
from radd.kernel import changes as kchanges, registries

# `Event` is re-exported as the PUBLIC consumer payload type (RADD-886); the ratchet test
# bans `events.models` outside this module.
from . import ledger
from .models import ConsumerOffset, Event
from .quiet import AutomationCause, automated, current_cause, is_automated, is_quiet, quiet, run_cause
from .types import EventSource

__all__ = [
    "Event", "quiet", "is_quiet", "automated", "is_automated",
    "AutomationCause", "current_cause", "run_cause", "derived_from",
]  # re-exported public seam (see above)


@contextmanager
def derived_from(event: Event, *, silent: bool = False):
    """Restore provenance when a consumer emits consequences of an outbox event.

    This is the same action continuing in another worker, not another automation
    run, so the depth is preserved. Each scope restores the previous context.
    """
    cause = AutomationCause(event.automation_rule_id, event.automation_depth or 1)
    with automated(bool(event.automated), cause=cause), quiet(silent or bool(event.silent)):
        yield


async def emit(
    session: AsyncSession,
    *,
    event_type: StrEnum,
    entity_type: StrEnum,
    entity_id: object,
    actor_id: uuid.UUID | None = None,
    payload: dict[str, Any] | None = None,
    subjects: dict[str, Any] | None = None,
    changes: list[dict[str, Any]] | None = None,
    project_id: uuid.UUID | None = None,
    occurred_at: datetime | None = None,
    silent: bool | None = None,
    automated_cause: bool | None = None,
) -> None:
    """Append to the outbox inside the caller's transaction.

    `changes` is the `kernel.changes` diff (spec 123), written at the payload's top level. A
    type declaring `has_changes` must carry one: None raises `ChangesRequired`, `[]` means
    "nothing visible changed". `subjects` are IDS (RADD-923): `{"item": id}` becomes
    `payload["item"]`, the registered canonical ref. `occurred_at` backdates imports (naive
    UTC; `id` still orders the stream). `silent` defaults to being inside `events.quiet()`."""
    subjects = _with_own_subject(str(entity_type), entity_id, payload, subjects)
    payload = await _with_subjects(session, payload, subjects)
    payload = _with_changes(str(event_type), payload, changes)
    label = ledger.entity_label(str(entity_type), payload or {})
    cause = current_cause()
    if automated_cause is True and cause is None:
        cause = AutomationCause()
    elif automated_cause is False:
        cause = None
    event = Event(
        event_type=str(event_type),
        entity_type=str(entity_type),
        entity_id=str(entity_id),
        actor_id=actor_id,
        payload=payload or {},
        silent=is_quiet() if silent is None else silent,
        automated=cause is not None,
        automation_rule_id=cause.rule_id if cause else None,
        automation_depth=cause.depth if cause else 0,
        # Spec 123: the ledger columns, derived — an emitter declares nothing new.
        project_id=project_id or ledger.project_of(payload or {}),
        entity_label=label,
        search_text=ledger.search_text(str(event_type), label, payload or {}),
    )
    if occurred_at is not None:
        event.created_at = occurred_at.replace(tzinfo=None)
    session.add(event)


def _with_own_subject(
    entity_type: str,
    entity_id: object,
    payload: dict[str, Any] | None,
    subjects: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Spec 123: an event about an entity with a registered ref carries that
    ref, whether or not the emitter thought to pass it — the ledger's label
    and the SPA's link both read it. Costs one lookup for the emitters that
    did not already; items and pages already do."""
    if entity_type in (subjects or {}) or entity_type in (payload or {}):
        return subjects
    if entity_type not in registries.entity_refs:
        return subjects
    return {**(subjects or {}), entity_type: entity_id}


class ChangesRequired(RuntimeError):
    """An emitter promised a diff (`EventTypeSpec.has_changes`) and sent none."""


def _with_changes(
    event_type: str, payload: dict[str, Any] | None, changes: list[dict[str, Any]] | None
) -> dict[str, Any] | None:
    if changes is not None:
        return {**(payload or {}), kchanges.CHANGES_KEY: changes}
    spec = registries.event_types.get(event_type)
    if spec is not None and spec.has_changes and kchanges.CHANGES_KEY not in (payload or {}):
        raise ChangesRequired(
            f"{event_type} declares has_changes but was emitted without changes= — "
            "pass the kernel.changes diff (or [] when nothing visible changed)"
        )
    return payload


async def _with_subjects(
    session: AsyncSession,
    payload: dict[str, Any] | None,
    subjects: dict[str, Any] | None,
) -> dict[str, Any]:
    """Expand `{entity_type: id}` into canonical refs on the payload (RADD-923). An
    unregistered subject is a programming error (the loader refuses undeclared ones): raise in
    debug, degrade to a bare id in production — the event is a side effect of someone else's
    write, and a thin payload beats failing it."""
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


async def latest_ref(session: AsyncSession, entity_type: str) -> dict[str, Any] | None:
    """The most recent subject REF of this entity type any event carried
    (RADD-1331) — a real `{id, key, title, …}` to show which fields a ref of
    that type has, without inventing one. None when no event ever named one."""
    row = await session.scalar(
        select(Event.payload[entity_type])
        .where(Event.payload.has_key(entity_type))
        .order_by(Event.id.desc())
        .limit(1)
    )
    return row if isinstance(row, dict) and row.get("id") else None


async def query_events(
    session: AsyncSession,
    *,
    entity_type: str | None = None,
    entity_id: str | None = None,
    event_types: Sequence[str] | None = None,
    exclude_event_types: Sequence[str] | None = None,
    actor_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    changed_field: str | None = None,
    source: EventSource | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    q: str | None = None,
    ascending: bool = False,
    before_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Event]:
    """Filtered read of the (append-only) audit log; filters AND, newest first by default.

    `q` matches `search_text` through the `d123ledger` trigram index; `changed_field` is a
    containment probe over `payload -> 'changes'` (GIN). `exclude_event_types` drops what
    `EventTypeSpec.audited=False` marks as noise."""
    conditions = []
    if before_id is not None:
        conditions.append(Event.id < before_id)
    if q:
        conditions.append(Event.search_text.ilike(ilike_term(q)))
    if entity_type is not None:
        # One type, or several — a settings page edits users AND service
        # accounts, and its history link asks for both (spec 123).
        wanted = [t.strip() for t in entity_type.split(",") if t.strip()]
        conditions.append(
            Event.entity_type == wanted[0] if len(wanted) == 1 else Event.entity_type.in_(wanted)
        )
    if entity_id is not None:
        conditions.append(Event.entity_id == entity_id)
    if event_types:
        conditions.append(Event.event_type.in_(list(event_types)))
    if exclude_event_types:
        conditions.append(Event.event_type.not_in(list(exclude_event_types)))
    if actor_id is not None:
        conditions.append(Event.actor_id == actor_id)
    if project_id is not None:
        conditions.append(Event.project_id == project_id)
    if changed_field:
        conditions.append(Event.payload[kchanges.CHANGES_KEY].contains([{"field": changed_field}]))
    if source is EventSource.PEOPLE:
        conditions.append(Event.actor_id.is_not(None))
        conditions.append(Event.automated.is_(False))
    elif source is EventSource.AUTOMATIONS:
        conditions.append(Event.automated.is_(True))
    elif source is EventSource.SYSTEM:
        conditions.append(Event.actor_id.is_(None))
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


async def resume_at_head(session: AsyncSession, consumers: Iterable[str]) -> int:
    """Move each named consumer's cursor to the stream head and return it — how a
    `ConsumerResume.HEAD` consumer resumes on re-enable (RADD-1372), in the enabling
    transaction, so the skipped stretch is exactly the time the plugin was off."""
    head = await latest_event_id(session)
    for name in consumers:
        await set_offset(session, name, head)
    return head


async def consumer_status(session: AsyncSession) -> list[dict[str, Any]]:
    """Every consumer's cursor vs the stream head: lag, and seconds since it moved (computed
    by the clock that wrote `updated_at`). `registered` (RADD-1093) says whether the CODE
    still runs it, so a renamed consumer's leftover cursor reads as residue, not a stall.
    Never auto-deleted: a disabled plugin's consumer is unregistered too."""
    descriptions = {name: text for plugin in registries.plugins.values()
                    for name, text in plugin.consumer_descriptions}
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
            "description": descriptions.get(name, ""),
            "last_event_id": last_event_id,
            "stream_head": head,
            "lag": max(0, head - last_event_id),
            "seconds_since_update": max(0, int(seconds or 0)),
            "registered": name in registries.consumer_names,
        }
        for name, last_event_id, seconds in result.all()
    ]
