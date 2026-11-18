"""The event-consumer runner (RADD-1538): one loop body, one failure behaviour.

A consumer DECLARES what it is (`Consumer`) and `run` owns the rest, so a
handler that raises is never just logged and lost, and a second worker process
never delivers a batch twice:

- **the claim** — the cursor row is taken `FOR UPDATE SKIP LOCKED` for the
  tick. A worker that finds it taken does nothing this tick, so two processes
  never deliver the same batch;
- **the handler** runs per event inside a savepoint. One that raises rolls back
  only its own writes;
- **the failure** is recorded in `consumer_failures` with the error. An
  at-least-once consumer's event is retried with backoff (by the same loop,
  before it reads on) and marked dead after `event_consumer_max_attempts`; an
  at-most-once consumer's is recorded dead at once — never retried, but no
  longer invisible, and an operator can replay or discard it;
- **the cursor** advances with the batch, in the same transaction as the
  handlers' writes and the failure rows.

Retried events are delivered out of order, after later ones. Every consumer
here tolerates that: they act on the event's subject as it is now.

Head-seeded two-phase consumers (`runner.run_head_seeded`) share the claim and
the failure table through `claim` and `record_failure`.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from radd.clock import utcnow
from radd.config import settings
from radd.db import SessionLocal

from . import service
from .models import ConsumerFailure, ConsumerOffset, Event
from .service import EventCursor

logger = logging.getLogger(__name__)

#: How much of an exception is kept on the failure row.
_ERROR_CHARS = 2000


class Delivery(StrEnum):
    """What a consumer promises about an event whose handler raised."""

    #: Retried with backoff, then dead. The handler must tolerate a repeat.
    AT_LEAST_ONCE = "at_least_once"
    #: Never retried (a duplicate would be worse than a miss); recorded dead.
    AT_MOST_ONCE = "at_most_once"


class FirstStart(StrEnum):
    """Where a consumer with no cursor yet begins."""

    BEGINNING = "beginning"  # work through the backlog (an index, a projection)
    HEAD = "head"  # only what happens from now on (anything that tells people)


class FailureStatus(StrEnum):
    PENDING = "pending"  # will be retried at `next_attempt_at`
    DEAD = "dead"  # out of attempts, or never retried: waits for an operator


Handler = Callable[[AsyncSession, Event], Awaitable[None]]


def _every_event(event: Event) -> bool:
    return True


@dataclass(frozen=True)
class Consumer:
    """A named reader of the stream. `handle` is called once per wanted event,
    inside a savepoint of the runner's transaction; raising marks the event
    failed and leaves the rest of the batch untouched."""

    name: str
    handle: Handler
    #: Read live at each tick, so a setting change needs no restart.
    batch_size: Callable[[], int]
    delivery: Delivery = Delivery.AT_LEAST_ONCE
    first_start: FirstStart = FirstStart.BEGINNING
    #: Events the consumer skips without calling the handler (the cursor still
    #: passes them): another family's types, a bulk import's `silent` rows.
    wants: Callable[[Event], bool] = _every_event


#: Every consumer that has run in this process, by name — how an operator's
#: replay finds the handler for a failure row.
_consumers: dict[str, Consumer] = {}


def register(consumer: Consumer) -> Consumer:
    _consumers[consumer.name] = consumer
    return consumer


async def claim(
    session: AsyncSession, name: str, first_start: FirstStart
) -> EventCursor | None:
    """Take `name`'s cursor for this transaction, or None when another worker
    holds it (nothing to do this tick). A consumer with no cursor yet gets one,
    at the head or at the beginning as it declared."""

    async def locked() -> ConsumerOffset | None:
        return (
            await session.execute(
                select(ConsumerOffset)
                .where(ConsumerOffset.name == name)
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()

    row = await locked()
    if row is None:
        exists = await session.scalar(
            select(ConsumerOffset.name).where(ConsumerOffset.name == name)
        )
        if exists is not None:
            return None  # held by another worker
        start = (
            await service.head_cursor(session) if first_start is FirstStart.HEAD else EventCursor()
        )
        # Two workers starting together both get here. The second one's insert
        # waits for the first to commit, writes nothing, and then reads the
        # cursor the first has already advanced.
        await session.execute(
            insert(ConsumerOffset)
            .values(name=name, last_xact_id=start.xact_id, last_event_id=start.event_id)
            .on_conflict_do_nothing()
        )
        logger.info("%s: first start — cursor at the %s", name, first_start.value)
        row = await locked()
        if row is None:
            return None
    return EventCursor(row.last_xact_id, row.last_event_id)


def _backoff(attempts: int) -> timedelta:
    """30 s, 1 min, 2 min, 4 min … capped — long enough for a dependency to come back."""
    seconds = settings.event_consumer_retry_base_seconds * 2 ** (attempts - 1)
    return timedelta(seconds=min(seconds, settings.event_consumer_retry_max_seconds))


async def record_failure(
    session: AsyncSession,
    name: str,
    event_id: int,
    error: BaseException,
    delivery: Delivery,
) -> None:
    """Note that `name` failed on `event_id`: a new row, or one more attempt on
    the row it already has."""
    now = utcnow()
    row = await session.scalar(
        select(ConsumerFailure).where(
            ConsumerFailure.consumer == name, ConsumerFailure.event_id == event_id
        )
    )
    if row is None:
        row = ConsumerFailure(consumer=name, event_id=event_id, attempts=0, first_failed_at=now)
        session.add(row)
    row.attempts += 1
    row.error = f"{type(error).__name__}: {error}"[:_ERROR_CHARS]
    row.last_failed_at = now
    exhausted = row.attempts >= settings.event_consumer_max_attempts
    if delivery is Delivery.AT_MOST_ONCE or exhausted:
        row.status = FailureStatus.DEAD.value
        row.next_attempt_at = None
        logger.error("%s: event %s is dead after %s attempt(s)", name, event_id, row.attempts)
    else:
        row.status = FailureStatus.PENDING.value
        row.next_attempt_at = now + _backoff(row.attempts)
    await session.flush()


async def _deliver(session: AsyncSession, consumer: Consumer, event: Event) -> bool:
    try:
        async with session.begin_nested():
            await consumer.handle(session, event)
    except Exception as error:  # noqa: BLE001 — a handler may raise anything
        logger.exception("%s: failed on event %s (%s)", consumer.name, event.id, event.event_type)
        await record_failure(session, consumer.name, event.id, error, consumer.delivery)
        return False
    return True


async def _retry_due(session: AsyncSession, consumer: Consumer) -> int:
    """Hand the consumer its failed events whose backoff has passed."""
    due = (
        await session.execute(
            select(ConsumerFailure)
            .where(
                ConsumerFailure.consumer == consumer.name,
                ConsumerFailure.status == FailureStatus.PENDING.value,
                ConsumerFailure.next_attempt_at <= utcnow(),
            )
            .order_by(ConsumerFailure.id)
            .limit(consumer.batch_size())
            .with_for_update(skip_locked=True)
        )
    ).scalars().all()
    for failure in due:
        event = await service.get_event(session, failure.event_id)
        if event is None or await _deliver(session, consumer, event):
            await session.delete(failure)  # delivered, or its event is gone
    return len(due)


async def run_in(session: AsyncSession, consumer: Consumer) -> int:
    """One tick inside the CALLER's transaction: retry what is due, read the
    next batch, hand each wanted event to the handler, advance. Returns how
    many events it dealt with; the caller commits."""
    register(consumer)
    cursor = await claim(session, consumer.name, consumer.first_start)
    if cursor is None:
        return 0
    retried = await _retry_due(session, consumer)
    batch = await service.read_after(session, cursor, consumer.batch_size())
    for event in batch:
        if consumer.wants(event):
            await _deliver(session, consumer, event)
    if batch:
        await service.set_offset(session, consumer.name, batch[-1])
    return len(batch) + retried


async def run(consumer: Consumer, session_factory=SessionLocal) -> int:
    """One tick in a transaction of its own — what a consumer's loop calls."""
    async with session_factory() as session:
        dealt_with = await run_in(session, consumer)
        await session.commit()
        return dealt_with


# --- the operator's side: look, replay, discard ---------------------------------


class ReplayUnavailable(RuntimeError):
    """The failure's consumer is not running in this process (its plugin is
    disabled, or it lives in the worker process)."""


async def list_failures(
    session: AsyncSession,
    *,
    consumer: str | None = None,
    status: FailureStatus | None = None,
    limit: int = 100,
) -> list[ConsumerFailure]:
    query = select(ConsumerFailure).order_by(ConsumerFailure.id.desc()).limit(limit)
    if consumer:
        query = query.where(ConsumerFailure.consumer == consumer)
    if status is not None:
        query = query.where(ConsumerFailure.status == status.value)
    return list((await session.execute(query)).scalars())


async def failure_counts(session: AsyncSession) -> dict[tuple[str, str], int]:
    """`{(consumer, status): n}` — the monitoring page and `/metrics` read this."""
    rows = await session.execute(
        select(ConsumerFailure.consumer, ConsumerFailure.status, func.count()).group_by(
            ConsumerFailure.consumer, ConsumerFailure.status
        )
    )
    return {(name, status): count for name, status, count in rows}


async def replay(session: AsyncSession, failure: ConsumerFailure) -> bool:
    """Deliver a failed event again, now. True = it went through and the row is
    gone; False = it failed again (the row says how)."""
    from radd.kernel import registries

    from . import runner

    event = await service.get_event(session, failure.event_id)
    if event is None:
        await session.delete(failure)
        return True
    if failure.consumer not in registries.consumer_names:
        raise ReplayUnavailable(f"{failure.consumer} is not enabled on this instance")
    consumer = _consumers.get(failure.consumer)
    if consumer is not None:
        delivered = await _deliver(session, consumer, event)
    elif failure.consumer in runner.head_seeded:
        delivered = await runner.replay(session, failure.consumer, event)
    else:
        raise ReplayUnavailable(f"{failure.consumer} has not run in this process")
    if delivered:
        await session.delete(failure)
    return delivered
