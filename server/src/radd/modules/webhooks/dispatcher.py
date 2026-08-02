"""In-process delivery loop. Moves to the dedicated worker entrypoint when that lands."""

import httpx

from radd.config import settings
from radd.db import SessionLocal
from radd.worker import PeriodicLoop

from . import service

# One client for the loop's lifetime (connection reuse); created lazily on the
# first tick, closed by stop() so a stop→start cycle gets a fresh one.
_client: httpx.AsyncClient | None = None


async def _run_once() -> None:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=settings.webhook_timeout)
    async with SessionLocal() as session:
        await service.fanout_events(session)
        await session.commit()
    async with SessionLocal() as session:
        await service.attempt_due(session, _client)
        await session.commit()


_loop = PeriodicLoop(
    _run_once,
    interval=lambda: settings.webhook_poll_interval,
    name="webhook-dispatcher",
    enabled=lambda: settings.run_workers,  # web-only process skips (spec 48 worker split)
)

start = _loop.start


async def stop() -> None:
    global _client
    await _loop.stop()
    if _client is not None:
        await _client.aclose()
        _client = None
