"""The socket a room serves (spec 122): pycrdt's `Channel` over Starlette's
WebSocket, carrying the two things the room itself must not know about.

* **The session cookie is re-validated** exactly as `realtime/router.py` does:
  on an ABSOLUTE deadline (`realtime_session_refresh_seconds` — inbound traffic
  cannot extend a revoked session) and on inbound frames, throttled to
  `collab_frame_auth_seconds` because an editor's keystrokes arrive as frames
  and a session lookup per keystroke would put the database behind the cursor.
* **Current page access is checked before every outbound frame and inbound
  document update**, as well as on the idle deadline. A valid login must never
  preserve an old page/ancestor/space grant. Checks use fresh DB sessions.
* **An observer's document updates are dropped here**, before the room sees
  them: `YRoom.serve` applies every sync frame it is handed, so the role is
  enforced by what the iterator yields, not by anything the room decides.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable

from anyio import Lock
from fastapi import WebSocket, WebSocketDisconnect
from pycrdt import Channel

from radd.config import settings
from radd.db import SessionLocal
from radd.exceptions import ForbiddenError, NotFoundError
from radd.modules.auth import authz, service as auth
from radd.modules.pages import page_access

from .types import (
    WS_CLOSE_UNAUTHENTICATED,
    WS_CLOSE_SESSION_UNKNOWN,
    CollabRole,
    is_awareness_query,
    is_document_update,
)

logger = logging.getLogger(__name__)

#: RFC 6455 "policy violation" — a frame the protocol does not allow here.
_WS_CLOSE_POLICY = 1008


class RoomChannel(Channel):
    def __init__(
        self, websocket: WebSocket, *, path: str, token: str, user_id: uuid.UUID, role: CollabRole
    ) -> None:
        self._websocket = websocket
        self._path = path
        self._page_id = uuid.UUID(path)
        self._token = token
        self._user_id = user_id
        self.role = role
        self._send_lock = Lock()
        self._validated_at = time.monotonic()
        self.closed = False
        #: Every awareness state the room holds, as one frame — set by the room
        #: at connect; answers the provider's query (`YRoom.serve` does not).
        self.awareness_snapshot: Callable[[], bytes | None] = lambda: None

    @property
    def path(self) -> str:
        return self._path

    async def send(self, message: bytes) -> None:
        # A dead socket must not take the room's broadcast loop with it; the
        # receive side sees the disconnect and ends this client's service.
        if self.closed:
            return
        async with self._send_lock:
            # Check after waiting for the transport lock: a slow previous send
            # must not leave a queued frame carrying an old authorization verdict.
            if not await self._revalidate():
                return
            try:
                await self._websocket.send_bytes(message)
            except Exception:  # noqa: BLE001 — closed mid-send
                self.closed = True

    async def recv(self) -> bytes:
        return bytes(await self._websocket.receive_bytes())

    async def __anext__(self) -> bytes:
        while True:
            if self.closed:
                raise StopAsyncIteration()
            deadline = self._validated_at + settings.realtime_session_refresh_seconds
            try:
                async with asyncio.timeout(max(0.0, deadline - time.monotonic())):
                    frame = await self.recv()
            except TimeoutError:
                if not await self._revalidate():
                    raise StopAsyncIteration() from None
                continue
            except WebSocketDisconnect:
                self.closed = True
                raise StopAsyncIteration() from None
            except Exception:  # noqa: BLE001 — a text frame, a broken socket
                await self._close(_WS_CLOSE_POLICY)
                raise StopAsyncIteration() from None
            if is_document_update(frame) or time.monotonic() - self._validated_at >= settings.collab_frame_auth_seconds:
                if not await self._revalidate():
                    raise StopAsyncIteration()
            if is_awareness_query(frame):
                snapshot = self.awareness_snapshot()
                if snapshot is not None:
                    await self.send(snapshot)
                continue  # answered here; the room has no handler for it
            if self.role == CollabRole.OBSERVER and is_document_update(frame):
                continue  # relayed nowhere: an observer cannot change the document
            return frame

    async def _revalidate(self) -> bool:
        if self.closed:
            return False
        async with SessionLocal() as session:
            resolved = await auth.resolve_session_users(session, self._token)
            current = (resolved[1] or resolved[0]) if resolved else None
            if current is None or current.id != self._user_id:
                await self._close(WS_CLOSE_UNAUTHENTICATED)
                return False
            permission = (
                authz.Permission.PAGE_WRITE
                if self.role == CollabRole.EDITOR else authz.Permission.PAGE_READ
            )
            try:
                await page_access.guard_page(session, current, self._page_id, permission)
            except (ForbiddenError, NotFoundError):
                await self._close(WS_CLOSE_SESSION_UNKNOWN)
                return False
        self._validated_at = time.monotonic()
        return True

    async def _close(self, code: int) -> None:
        self.closed = True
        try:
            await self._websocket.close(code=code)
        except Exception:  # noqa: BLE001 — already gone
            pass
