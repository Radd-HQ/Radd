"""Stale-while-revalidate module snapshots (RADD-899).

The write-through pattern ("refreshed on write + at startup") answers correctly
in the process that WROTE — and serves the old value in every OTHER replica
until restart. These snapshots exist because `CapabilitySpec.check` is sync and
cannot query, so the fix is not "query instead": a sync read returns the
current value and, once the TTL has lapsed, schedules ONE background refresh
through the loader (which owns its own session). Bounded staleness — default
`settings.snapshot_ttl_seconds` — replaces unbounded, and the
per-request-query win the caches exist for stays.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Generic, TypeVar

from radd.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")


class Snapshot(Generic[T]):
    """One cached value: sync `get()` (stale-while-revalidate), write-through
    `set()` for the process that changed the data, awaitable `refresh()` for
    startup warms."""

    def __init__(
        self,
        name: str,
        loader: Callable[[], Awaitable[T]],
        *,
        initial: T,
        ttl_seconds: float | None = None,
    ) -> None:
        self._name = name
        self._loader = loader
        self._value: T = initial
        self._loaded_at = 0.0  # epoch-of-monotonic zero: first read refreshes
        self._ttl = settings.snapshot_ttl_seconds if ttl_seconds is None else ttl_seconds
        self._refreshing: asyncio.Task | None = None

    def set(self, value: T) -> None:
        self._value = value
        self._loaded_at = time.monotonic()

    def get(self) -> T:
        """The current value. When stale, ONE background refresh is scheduled
        (deduped); outside a running loop the current value simply stands —
        callers are request/capability paths, which always have a loop."""
        stale = time.monotonic() - self._loaded_at > self._ttl
        if stale and (self._refreshing is None or self._refreshing.done()):
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return self._value
            self._refreshing = loop.create_task(
                self.refresh(), name=f"snapshot-refresh:{self._name}"
            )
        return self._value

    async def refresh(self) -> None:
        try:
            self.set(await self._loader())
        except Exception:  # a failed refresh serves the previous value, loudly
            logger.exception("snapshot %r refresh failed — keeping the previous value", self._name)
