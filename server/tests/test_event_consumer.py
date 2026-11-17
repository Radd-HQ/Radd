"""The event-consumer runner's promises (RADD-1538).

Before it, a handler that raised was logged and the cursor moved on: the
notification, webhook, index update or automation run was simply gone. And no
consumer locked its cursor, so a second worker would have delivered everything
twice. Three things are asserted here because every consumer depends on them:

- a handler that fails once is retried and its event is then delivered;
- one that always fails ends up dead — kept, with its error, replayable;
- two runners on one database deliver each event once between them.
"""

import asyncio
import uuid
from datetime import timedelta
from enum import StrEnum

from sqlalchemy import select, text, update

from radd.clock import utcnow
from radd.config import settings
from radd.db import SessionLocal
from radd.kernel import registries
from radd.modules.events import consumer as consumers, runner, service as events
from radd.modules.events.models import ConsumerFailure


class _Kind(StrEnum):
    PROBE = "consumer.probe"


def _name() -> str:
    return f"test.{uuid.uuid4().hex[:12]}"


async def _emit(session, tag: str) -> None:
    await events.emit(
        session,
        event_type=_Kind.PROBE,
        entity_type=_Kind.PROBE,
        entity_id=tag,
        payload={"tag": tag},
        silent=True,
    )
    await session.flush()


def _probe(name: str, handle, **overrides) -> consumers.Consumer:
    return consumers.Consumer(
        name=name,
        handle=handle,
        batch_size=lambda: 50,
        first_start=consumers.FirstStart.HEAD,
        wants=lambda event: event.event_type == _Kind.PROBE.value,
        **overrides,
    )


async def _failures(session, name: str) -> list[ConsumerFailure]:
    rows = await session.execute(select(ConsumerFailure).where(ConsumerFailure.consumer == name))
    return list(rows.scalars())


async def _make_due(session, name: str) -> None:
    await session.execute(
        update(ConsumerFailure)
        .where(ConsumerFailure.consumer == name)
        .values(next_attempt_at=utcnow() - timedelta(seconds=1))
    )


async def test_a_handler_that_fails_once_is_retried_and_then_delivers(db):
    name, delivered, calls = _name(), [], []

    async def flaky(session, event):
        calls.append(event.payload["tag"])
        if len(calls) == 1:
            raise RuntimeError("the mail server is restarting")
        delivered.append(event.payload["tag"])

    consumer = _probe(name, flaky)
    await consumers.run_in(db, consumer)  # first start: the cursor is seeded at the head
    await _emit(db, "one")
    await _emit(db, "two")

    assert await consumers.run_in(db, consumer) == 2
    # The failure cost the batch nothing: the second event went through, and the
    # cursor is past both — the failed one lives in the failure table, not behind it.
    assert delivered == ["two"]
    (failure,) = await _failures(db, name)
    assert failure.status == consumers.FailureStatus.PENDING.value
    assert failure.attempts == 1 and "restarting" in failure.error
    assert failure.next_attempt_at > utcnow()

    # Not due yet: the next tick leaves it alone.
    assert await consumers.run_in(db, consumer) == 0
    assert delivered == ["two"]

    await _make_due(db, name)
    assert await consumers.run_in(db, consumer) == 1
    assert delivered == ["two", "one"]
    assert await _failures(db, name) == []


async def test_a_handler_that_always_fails_goes_dead_and_can_be_replayed(db, monkeypatch):
    monkeypatch.setattr(settings, "event_consumer_max_attempts", 3)
    name, broken, delivered = _name(), [True], []

    async def handler(session, event):
        if broken[0]:
            raise ValueError("no such recipient")
        delivered.append(event.payload["tag"])

    consumer = _probe(name, handler)
    await consumers.run_in(db, consumer)
    await _emit(db, "lost")
    await consumers.run_in(db, consumer)
    for _ in range(2):
        await _make_due(db, name)
        await consumers.run_in(db, consumer)

    (failure,) = await _failures(db, name)
    assert failure.status == consumers.FailureStatus.DEAD.value
    assert failure.attempts == 3 and failure.next_attempt_at is None
    # Dead means left alone: no further automatic attempt.
    await consumers.run_in(db, consumer)
    assert (await _failures(db, name))[0].attempts == 3

    # An operator fixes the cause and replays it.
    registries.consumer_names.add(name)
    try:
        assert await consumers.replay(db, failure) is False  # still broken: the row stays
        assert (await _failures(db, name))[0].attempts == 4
        broken[0] = False
        assert await consumers.replay(db, failure) is True
    finally:
        registries.consumer_names.discard(name)
    await db.flush()
    assert delivered == ["lost"] and await _failures(db, name) == []


async def test_an_at_most_once_consumer_records_the_failure_and_never_retries(db):
    name, calls = _name(), []

    async def handler(session, event):
        calls.append(event.id)
        raise RuntimeError("posted to chat, then failed")

    consumer = _probe(name, handler, delivery=consumers.Delivery.AT_MOST_ONCE)
    await consumers.run_in(db, consumer)
    await _emit(db, "once")
    await consumers.run_in(db, consumer)
    await consumers.run_in(db, consumer)

    (failure,) = await _failures(db, name)
    assert failure.status == consumers.FailureStatus.DEAD.value and failure.attempts == 1
    assert len(calls) == 1


async def test_a_failing_handlers_own_writes_are_rolled_back(db):
    """The savepoint: what a handler wrote before it raised must not commit with
    the batch, or a retry would do it twice."""
    name = _name()

    async def handler(session, event):
        await _emit(session, "written-then-failed")
        raise RuntimeError("after the write")

    consumer = _probe(name, handler)
    await consumers.run_in(db, consumer)
    await _emit(db, "trigger")
    await consumers.run_in(db, consumer)
    leaked = await db.scalar(
        text("SELECT count(*) FROM events WHERE entity_id = 'written-then-failed'")
    )
    assert leaked == 0


async def test_two_workers_deliver_each_event_once_between_them():
    """Real transactions: two runners tick at the same moment against one
    database. The cursor row is claimed FOR UPDATE SKIP LOCKED, so one of them
    takes the batch and the other does nothing — not the same batch twice."""
    name = _name()
    tags = [uuid.uuid4().hex for _ in range(6)]
    seen: list[str] = []

    async def slow(session, event):
        await asyncio.sleep(0.05)  # hold the claim long enough to overlap
        seen.append(event.payload["tag"])

    consumer = _probe(name, slow)
    try:
        await consumers.run(consumer)  # seed at the head, committed
        async with SessionLocal() as session:
            for tag in tags:
                await _emit(session, tag)
            await session.commit()

        first, second = await asyncio.gather(consumers.run(consumer), consumers.run(consumer))
        assert sorted([first, second])[0] == 0, "both workers took the batch"
        assert sorted(tag for tag in seen if tag in tags) == sorted(tags)
        # Nothing is left for a later tick, from either worker.
        assert await consumers.run(consumer) == 0
        assert len([tag for tag in seen if tag in tags]) == len(tags)
    finally:
        async with SessionLocal() as session:
            await session.execute(
                text("DELETE FROM events WHERE event_type = :kind AND entity_id = ANY(:tags)"),
                {"kind": _Kind.PROBE.value, "tags": tags},
            )
            await session.execute(
                text("DELETE FROM consumer_offsets WHERE name = :name"), {"name": name}
            )
            await session.execute(
                text("DELETE FROM consumer_failures WHERE consumer = :name"), {"name": name}
            )
            await session.commit()


async def test_a_two_phase_consumers_failed_plan_is_recorded_not_dropped(monkeypatch):
    """`run_head_seeded` (mail, surveys, cascades) is at-most-once by design; a
    plan that raises used to be a log line."""
    name, tag = _name(), uuid.uuid4().hex

    async def plan(session, event):
        if event.payload.get("tag") == tag:
            raise RuntimeError("template missing")
        return None

    async def deliver(plans):
        raise AssertionError("nothing was planned")

    try:
        await runner.run_head_seeded(name, batch_size=50, plan=plan, deliver=deliver)
        async with SessionLocal() as session:
            await events.emit(
                session, event_type=_Kind.PROBE, entity_type=_Kind.PROBE, entity_id=tag,
                payload={"tag": tag},
            )
            await session.commit()
        await runner.run_head_seeded(name, batch_size=50, plan=plan, deliver=deliver)
        async with SessionLocal() as session:
            (failure,) = await _failures(session, name)
            assert failure.status == consumers.FailureStatus.DEAD.value
            assert "template missing" in failure.error
    finally:
        async with SessionLocal() as session:
            for statement, value in (
                ("DELETE FROM events WHERE entity_id = :v", tag),
                ("DELETE FROM consumer_offsets WHERE name = :v", name),
                ("DELETE FROM consumer_failures WHERE consumer = :v", name),
            ):
                await session.execute(text(statement), {"v": value})
            await session.commit()
