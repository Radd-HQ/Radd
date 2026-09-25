"""RADD-1328: a third-party event consumer written against `radd.sdk` ALONE.

The SDK exported `read_events` and `emit_event` and nothing else, so a plugin
that wanted to follow the stream had to import `radd.modules.events.*`
internals for its cursor. Everything below is reached through `radd.sdk`; the
only other imports are the test's own database plumbing.
"""

import uuid
from enum import StrEnum

from sqlalchemy import text

from radd import sdk
from radd.db import SessionLocal


class AcmeEvent(StrEnum):
    PINGED = "acme.pinged"


class AcmeEntity(StrEnum):
    PING = "acme_ping"


async def test_a_consumer_runs_on_the_sdk_alone():
    name = f"acme.consumer.{uuid.uuid4().hex[:8]}"
    seen: list[str] = []

    async def plan(session, event):
        return event.payload.get("tag") if event.event_type == AcmeEvent.PINGED else None

    async def deliver(plans):
        seen.extend(plans)

    try:
        # First start seeds at the stream head: the historical backlog is not replayed.
        assert await sdk.run_consumer(name, batch_size=50, plan=plan, deliver=deliver) == 0
        async with SessionLocal() as session:
            assert await sdk.offset_exists(session, name)
            head = await sdk.get_offset(session, name)

        tag = uuid.uuid4().hex
        async with SessionLocal() as session:
            await sdk.emit_event(
                session, event_type=AcmeEvent.PINGED, entity_type=AcmeEntity.PING,
                entity_id=uuid.uuid4(), payload={"tag": tag},
            )
            await session.commit()

        assert await sdk.run_consumer(name, batch_size=50, plan=plan, deliver=deliver) >= 1
        assert tag in seen
        async with SessionLocal() as session:
            assert await sdk.get_offset(session, name) > head
            # A consumer can also move its own cursor (a replay, a skip).
            await sdk.set_offset(session, name, head)
            await session.commit()
            assert await sdk.get_offset(session, name) == head
    finally:
        async with SessionLocal() as session:
            await session.execute(text("DELETE FROM consumer_offsets WHERE name = :n"), {"n": name})
            await session.commit()
