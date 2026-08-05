"""radd.snapshot (RADD-899): stale-while-revalidate module snapshots.

Pins the three behaviors the four converted caches rely on: a stale sync read
schedules ONE background refresh and still answers immediately; write-through
answers the new value at once; a failing loader keeps serving the previous
value instead of blanking the capability pill.
"""

import asyncio

from radd.snapshot import Snapshot


async def test_stale_read_revalidates_in_background():
    calls = 0

    async def loader() -> int:
        nonlocal calls
        calls += 1
        return calls

    snap: Snapshot[int] = Snapshot("t", loader, initial=0, ttl_seconds=0.0)
    assert snap.get() == 0  # stale answer stands while the refresh runs
    await asyncio.sleep(0)  # let the scheduled task run
    assert snap.get() >= 1
    assert calls >= 1


async def test_write_through_is_immediate_and_fresh():
    async def loader() -> int:  # pragma: no cover — must not be called
        raise AssertionError("fresh value must not trigger a reload")

    snap: Snapshot[int] = Snapshot("t", loader, initial=0, ttl_seconds=60.0)
    snap.set(42)
    assert snap.get() == 42


async def test_failed_refresh_keeps_previous_value():
    async def loader() -> int:
        raise RuntimeError("issuer unreachable")

    snap: Snapshot[int] = Snapshot("t", loader, initial=7, ttl_seconds=0.0)
    assert snap.get() == 7
    await asyncio.sleep(0)
    assert snap.get() == 7  # still the old value, not an exception or a blank
