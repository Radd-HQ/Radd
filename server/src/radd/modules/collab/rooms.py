"""Rooms (spec 122): one live Yjs document per page, in this process.

A `Room` wraps pycrdt-websocket's `YRoom` (the sync/awareness protocol and the
broadcast loop) and adds what the product needs around it: the sessions that
may connect and in which role, the ONE seed grant an empty document hands out,
the debounced persistence tagged with the page version it corresponds to, and
the idle timer that drops an empty room from memory.

The hub is the module's only state. It is per-process — see docs/deploy.md.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pycrdt import Doc, TransactionEvent, create_awareness_message
from pycrdt.websocket import YRoom
from sqlalchemy.exc import IntegrityError

from radd.config import settings

from . import store
from .channel import RoomChannel
from .types import EMPTY_UPDATE, WS_CLOSE_DOCUMENT_REPLACED, CollabRole

logger = logging.getLogger(__name__)


@dataclass
class CollabSession:
    """A `join` — the right to connect to a page's room as `role`."""

    id: uuid.UUID
    user_id: uuid.UUID
    role: CollabRole
    connected: bool = False


class Room:
    def __init__(
        self,
        page_id: uuid.UUID,
        page_version: int,
        doc: Doc,
        *,
        has_content: bool,
        on_idle: Callable[[Room], Awaitable[None]],
    ) -> None:
        self.page_id = page_id
        self.page_version = page_version
        self.ydoc = doc
        self.has_content = has_content
        self.yroom = YRoom(ydoc=doc, log=logger, exception_handler=self._room_exception)
        self.sessions: dict[uuid.UUID, CollabSession] = {}
        self.channels: dict[uuid.UUID, RoomChannel] = {}
        self.seed_holder: uuid.UUID | None = None
        self._seed_granted_at = 0.0
        self._on_idle = on_idle
        self._dirty = False
        self._persist_lock = asyncio.Lock()
        self._stopped = False
        self._run_task: asyncio.Task | None = None
        self._persist_task: asyncio.Task | None = None
        self._idle_task: asyncio.Task | None = None
        self._subscription = None

    # --- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        self._run_task = asyncio.create_task(self.yroom.start())
        await self.yroom.started.wait()
        self._subscription = self.ydoc.observe(self._on_update)
        self._schedule_idle()  # opened by a join nobody follows up on → still dropped

    async def stop(self, *, close_code: int | None = None, persist: bool = True) -> None:
        if self._stopped:
            return
        self._stopped = True
        _cancel(self._idle_task)
        _cancel(self._persist_task)
        if persist:
            await self.persist()
        if self._subscription is not None:
            self.ydoc.unobserve(self._subscription)
        if close_code is not None:
            for channel in list(self.channels.values()):
                await channel._close(close_code)
        with contextlib.suppress(RuntimeError):
            await self.yroom.stop()
        if self._run_task is not None:
            with contextlib.suppress(asyncio.CancelledError, TimeoutError):
                await asyncio.wait_for(self._run_task, timeout=5)

    def _room_exception(self, exception: Exception, log: logging.Logger) -> bool:
        log.warning("collab room %s: %r", self.page_id, exception)
        return True

    # --- sessions ------------------------------------------------------------

    def join(self, user_id: uuid.UUID, role: CollabRole) -> tuple[CollabSession, bool]:
        """A new session, and whether it holds the seed grant. Only an EDITOR can
        seed (an observer's updates are dropped), only while the document is
        empty, and only one at a time — the grant lapses when its holder sends
        the first update, disconnects, or sits on it for
        `collab_seed_grant_seconds`."""
        session = CollabSession(id=uuid.uuid4(), user_id=user_id, role=role)
        self.sessions[session.id] = session
        seed = role == CollabRole.EDITOR and not self.has_content and self._seed_available()
        if seed:
            self.seed_holder = session.id
            self._seed_granted_at = time.monotonic()
        return session, seed

    def _seed_available(self) -> bool:
        if self.seed_holder is None or self.seed_holder not in self.sessions:
            return True
        return time.monotonic() - self._seed_granted_at > settings.collab_seed_grant_seconds

    def connect(self, session: CollabSession, channel: RoomChannel) -> None:
        session.connected = True
        self.channels[session.id] = channel
        channel.awareness_snapshot = self.awareness_snapshot
        _cancel(self._idle_task)

    def awareness_snapshot(self) -> bytes | None:
        """Everyone's awareness state as one frame, or None when the room holds
        none. Sent to a newcomer at connect and in answer to its query, so the
        saver election agrees from the first second rather than after the
        others' next heartbeat."""
        awareness = self.yroom.awareness
        client_ids = [cid for cid, state in awareness.states.items() if state]
        if not client_ids:
            return None
        return create_awareness_message(awareness.encode_awareness_update(client_ids))

    async def disconnect(self, session: CollabSession) -> None:
        session.connected = False
        self.channels.pop(session.id, None)
        if self.seed_holder == session.id:
            self.seed_holder = None  # the grant passes on
        if self._stopped:
            return
        if not self.channels:
            await self.flush()
            self._schedule_idle()

    def live_editors(self) -> list[CollabSession]:
        return [s for s in self.sessions.values() if s.connected and s.role == CollabRole.EDITOR]

    # --- the document ---------------------------------------------------------

    def _on_update(self, event: TransactionEvent) -> None:
        if event.update == EMPTY_UPDATE:
            return
        self.has_content = True
        self.seed_holder = None  # a non-empty document never grants
        self._dirty = True
        self._schedule_persist()

    def track_version(self, version: int) -> None:
        """The page was saved FROM this room: the stored state now corresponds to
        `version`. Re-persist so a restart resumes rather than discards."""
        self.page_version = version
        self._dirty = True
        self._schedule_persist()

    async def persist(self) -> None:
        """Serialised: a `flush` racing the debounce timer waits for the save in
        flight rather than returning while it is uncommitted."""
        async with self._persist_lock:
            if not self._dirty:
                return
            self._dirty = False  # an update landing mid-save sets it again
            try:
                await store.save(self.page_id, self.ydoc.get_update(), self.page_version)
            except IntegrityError:
                # The page is gone (hard-deleted under a live room): a state
                # with nothing to belong to is nothing to keep.
                logger.info("collab room %s: page deleted, state dropped", self.page_id)
            except BaseException:
                self._dirty = True
                raise

    async def flush(self) -> None:
        _cancel(self._persist_task)
        await self.persist()

    def _schedule_persist(self) -> None:
        if self._stopped:
            return
        _cancel(self._persist_task)
        self._persist_task = asyncio.create_task(self._persist_later())

    async def _persist_later(self) -> None:
        await asyncio.sleep(settings.collab_persist_debounce_seconds)
        # Rescheduling cancels this task; a save already under way must finish.
        await asyncio.shield(self.persist())

    def _schedule_idle(self) -> None:
        _cancel(self._idle_task)
        self._idle_task = asyncio.create_task(self._drop_later())

    async def _drop_later(self) -> None:
        await asyncio.sleep(settings.collab_room_idle_seconds)
        if not self.channels:
            await self._on_idle(self)


def _cancel(task: asyncio.Task | None) -> None:
    if task is not None and not task.done() and task is not asyncio.current_task():
        task.cancel()


class CollabHub:
    def __init__(self) -> None:
        self.rooms: dict[uuid.UUID, Room] = {}
        self._opening: dict[uuid.UUID, asyncio.Lock] = {}

    async def start(self) -> None:
        self.rooms = {}
        self._opening = {}

    async def shutdown(self) -> None:
        """Persist everything; rooms do not survive the process."""
        rooms, self.rooms = list(self.rooms.values()), {}
        for room in rooms:
            await room.stop()

    async def open(self, page_id: uuid.UUID, page_version: int) -> Room:
        room = self.rooms.get(page_id)
        if room is not None:
            return room
        lock = self._opening.setdefault(page_id, asyncio.Lock())
        async with lock:
            room = self.rooms.get(page_id)
            if room is not None:
                return room
            doc = Doc()
            has_content = False
            stored = await store.load(page_id)
            if stored is not None:
                state, stored_version = stored
                # Resume only what corresponds to the page as it is NOW; any
                # other state was outrun by a write that was not a room's.
                if stored_version == page_version and state != EMPTY_UPDATE:
                    doc.apply_update(state)
                    has_content = True
                else:
                    await store.discard(page_id)
            room = Room(page_id, page_version, doc, has_content=has_content, on_idle=self.drop)
            await room.start()
            self.rooms[page_id] = room
            return room

    async def join(
        self, page_id: uuid.UUID, page_version: int, user_id: uuid.UUID, role: CollabRole
    ) -> tuple[CollabSession, bool]:
        room = await self.open(page_id, page_version)
        return room.join(user_id, role)

    def room(self, page_id: uuid.UUID) -> Room | None:
        return self.rooms.get(page_id)

    def live_editors(self, page_id: uuid.UUID) -> list[CollabSession]:
        room = self.rooms.get(page_id)
        return room.live_editors() if room is not None else []

    def track_version(self, page_id: uuid.UUID, version: int) -> None:
        room = self.rooms.get(page_id)
        if room is not None:
            room.track_version(version)

    async def invalidate(self, page_id: uuid.UUID) -> None:
        """The body was replaced behind the room's back: drop it, discard the
        stored state, and send every client back through `join`."""
        room = self.rooms.pop(page_id, None)
        if room is not None:
            await room.stop(close_code=WS_CLOSE_DOCUMENT_REPLACED, persist=False)
        await store.discard(page_id)

    async def drop(self, room: Room) -> None:
        if self.rooms.get(room.page_id) is room:
            del self.rooms[room.page_id]
        await room.stop()


hub = CollabHub()
