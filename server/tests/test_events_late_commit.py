"""A transaction that commits late does not lose its event (RADD-1524).

An event id is taken when the row is flushed, not when its transaction commits.
The consumers used to read `id > cursor`: with id 100 still uncommitted and id
101 committed, a tick consumed 101, moved the cursor to 101, and the event at
100 was below every cursor from the moment it became visible. No error, just a
notification, webhook, automation run or search update that never happened.

These tests need REAL concurrent transactions, so they commit and clean up
after themselves instead of riding the rolled-back `db` fixture.
"""

import uuid
from enum import StrEnum

from sqlalchemy import text

from radd.db import SessionLocal
from radd.modules.events import service as events


class _Kind(StrEnum):
    LATE = "latecommit.probe"


async def _emit(session, tag: str) -> None:
    await events.emit(
        session,
        event_type=_Kind.LATE,
        entity_type=_Kind.LATE,
        entity_id=tag,
        payload={"tag": tag},
        silent=True,  # a real committed row: keep every delivering consumer away from it
    )
    await session.flush()


async def _drain(cursor, tags: set[str]):
    """One consumer tick's worth of reads: the probe events it saw, and where it stands."""
    seen: list[str] = []
    async with SessionLocal() as reader:
        while batch := await events.read_after(reader, cursor, 200):
            seen += [e.payload["tag"] for e in batch if e.payload.get("tag") in tags]
            cursor = events.cursor_of(batch[-1])
    return seen, cursor


async def _cleanup(tags: set[str]) -> None:
    async with SessionLocal() as session:
        await session.execute(
            text("DELETE FROM events WHERE event_type = :kind AND entity_id = ANY(:tags)"),
            {"kind": _Kind.LATE.value, "tags": list(tags)},
        )
        await session.commit()


async def test_an_event_flushed_first_and_committed_last_is_still_delivered():
    early, late = uuid.uuid4().hex, uuid.uuid4().hex
    tags = {early, late}
    try:
        async with SessionLocal() as reader:
            start = await events.head_cursor(reader)
        async with SessionLocal() as slow, SessionLocal() as fast:
            await _emit(slow, early)  # takes the LOWER id, stays open
            await _emit(fast, late)  # takes the higher id…
            await fast.commit()  # …and commits first

            seen, cursor = await _drain(start, tags)
            # The old cursor delivered `late` here and stepped past `early` for good.
            # Holding `late` back until nothing older can still appear is the fix.
            assert seen == [], f"read past an open transaction: {seen}"

            await slow.commit()
        seen, cursor = await _drain(cursor, tags)
        assert sorted(seen) == sorted(tags), f"an event was lost or repeated: {seen}"
        # And nothing is delivered twice on the next tick.
        again, _ = await _drain(cursor, tags)
        assert again == []
    finally:
        await _cleanup(tags)


async def test_an_older_transaction_that_emits_later_is_delivered_once():
    """The other interleaving: the transaction with the LOWER transaction id takes
    the HIGHER event id. Read in (transaction, id) order, both arrive, once each."""
    first, second = uuid.uuid4().hex, uuid.uuid4().hex
    tags = {first, second}
    try:
        async with SessionLocal() as reader:
            start = await events.head_cursor(reader)
        async with SessionLocal() as older, SessionLocal() as newer:
            # `older` gets its transaction id now, by writing anything at all.
            await older.execute(text("SELECT pg_current_xact_id()"))
            await _emit(newer, first)  # lower event id, higher transaction id, stays open
            await _emit(older, second)  # higher event id, lower transaction id
            await older.commit()

            seen, cursor = await _drain(start, tags)
            assert seen == [second]  # nothing older than it is still in flight

            await newer.commit()
        seen, cursor = await _drain(cursor, tags)
        assert seen == [first], f"the lower id behind the cursor was skipped: {seen}"
    finally:
        await _cleanup(tags)


async def test_a_cursor_from_before_the_column_resumes_where_it_was(db):
    """Rows written before `xact_id` existed carry 0, so `(0, N)` is exactly the
    old `last_event_id = N`: a deployed consumer neither replays nor skips."""
    name = f"latecommit.{uuid.uuid4().hex[:8]}"
    await _emit(db, "before")
    await _emit(db, "after")
    rows = [e for e in await events.read_after(db, events.EventCursor(), 10_000)
            if e.event_type == _Kind.LATE]
    before, after = rows[-2], rows[-1]

    await events.set_offset(db, name, before)
    assert await events.get_offset(db, name) == events.cursor_of(before)
    assert [e.id for e in await events.read_after(db, await events.get_offset(db, name), 10)] == [
        after.id
    ]
    # A bare id resolves through its row, so it carries that row's real transaction.
    assert await events.cursor_at(db, before.id) == events.cursor_of(before)
    assert await events.cursor_at(db, 0) == events.EventCursor()
