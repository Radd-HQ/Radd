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
from radd.modules.events.service import Event

from .hub import event_project_id, hub, query_targets, should_deliver, event_item_ids, InvalidationEvent

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
    semaphore = asyncio.Semaphore(settings.realtime_send_concurrency)

    async def send(websocket, info):
        targets = query_targets(info, event)
        if targets == []:
            return
        frame = message if targets is None else {**message, "queries": targets}
        async with semaphore:
            try:
                await asyncio.wait_for(websocket.send_json(frame), settings.realtime_send_timeout)
            except Exception:  # Socket errors/timeouts mean this reader must reconnect.
                hub.unregister(websocket)
                try:
                    await asyncio.wait_for(websocket.close(), settings.realtime_send_timeout)
                except Exception:  # A dead connection may also refuse the close frame.
                    pass

    await asyncio.gather(
        *(
            send(ws, info)
            for ws, info in list(hub.connections.items())
            if should_deliver(info, event)
        )
    )


def _coalesce(batch: list[Event]) -> list[InvalidationEvent]:
    """Frames invalidate snapshots; repeated changes in one poll need one ping."""
    pending = {}
    for event in batch:
        if not event.silent:
            key = (
                event.entity_type,
                event_project_id(event),
                (event.payload or {}).get("user_id")
                if event.entity_type == "notification"
                else None,
            )
            item_ids = event_item_ids(event)
            previous = pending.get(key)
            if previous is not None:
                # A broad event broadens the whole group. Otherwise retain
                # every changed record while still sending one frame per poll.
                item_ids = (previous.item_ids | item_ids
                            if previous.item_ids is not None and item_ids is not None else None)
            pending[key] = InvalidationEvent(
                event.entity_type, getattr(event, "event_type", ""), event.payload or {}, item_ids
            )
    return list(pending.values())


async def _run() -> None:
    async with SessionLocal() as session:
        last_id = await events.latest_event_id(session)
    while True:
        try:
            async with SessionLocal() as session:
                batch = await events.read_after(session, last_id, settings.realtime_batch)
            for event in _coalesce(batch):
                # Silent (bulk-import) events still advance the cursor, but are not
                # pushed — a 45k-issue import would otherwise flood every open tab.
                if not event.silent:
                    await _fan_out(event)
            if batch:
                last_id = batch[-1].id
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
            await asyncio.wait_for(websocket.close(), settings.realtime_send_timeout)
        except Exception:  # closing an already-dead socket has nothing to report
            pass
