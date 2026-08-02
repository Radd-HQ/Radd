"""Live tail of the event outbox → connected websockets.

Deliberately NOT a consumer_offsets consumer: realtime is ephemeral. It starts
at the stream head (events during downtime are covered by clients refetching on
reconnect) and keeps its cursor in memory only.
"""

import asyncio
import logging

from radd.config import settings
from radd.db import SessionLocal
from radd.modules.events import service as events
from radd.modules.events.models import Event

from .hub import hub, should_deliver

logger = logging.getLogger(__name__)

_task: asyncio.Task | None = None


def _message(event: Event) -> dict:
    """Compact, payload-free push: enough for the client to invalidate by entity."""
    return {
        "entity": event.entity_type,
        "event_type": event.event_type,
    }


async def _fan_out(event: Event) -> None:
    message = _message(event)
    # Snapshot: sends may drop connections, mutating the registry mid-iteration.
    for websocket, info in list(hub.connections.items()):
        if not should_deliver(info, event):
            continue
        try:
            await websocket.send_json(message)
        except Exception:
            hub.unregister(websocket)


async def _run() -> None:
    async with SessionLocal() as session:
        last_id = await events.latest_event_id(session)
    while True:
        try:
            async with SessionLocal() as session:
                batch = await events.read_after(session, last_id, settings.realtime_batch)
            for event in batch:
                # Silent (bulk-import) events still advance the cursor, but are not
                # pushed — a 45k-issue import would otherwise flood every open tab.
                if not event.silent:
                    await _fan_out(event)
                last_id = event.id
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("realtime broadcaster iteration failed")
        await asyncio.sleep(settings.realtime_poll_interval)


async def start() -> None:
    global _task
    _task = asyncio.create_task(_run(), name="realtime-broadcaster")


async def stop() -> None:
    if _task is not None:
        _task.cancel()
        await asyncio.gather(_task, return_exceptions=True)
    for websocket in list(hub.connections):
        hub.unregister(websocket)
        try:
            await websocket.close()
        except Exception:
            pass
