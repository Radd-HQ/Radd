"""`POST /collab/pages/{id}/join` + `WS /collab/pages/{id}?session=` (spec 122).

The join is an ordinary authenticated route: `CurrentUser` only — the anonymous
Actor never joins (spec 115 D9: nothing lets an anonymous caller write, and an
observer's awareness is a write to everyone else's screen). The socket then
authenticates the session COOKIE exactly as `realtime/router.py` does and
requires the `session` to be one this user was handed for this page.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import SessionLocal, get_session
from radd.modules.auth import authz, service as auth
from radd.modules.auth.deps import CurrentUser
from radd.modules.auth.types import SESSION_COOKIE_NAME
from radd.modules.pages import page_access

from .channel import RoomChannel
from .rooms import hub
from .schemas import CollabJoin, CollabJoinRead
from .types import WS_CLOSE_SESSION_UNKNOWN, WS_CLOSE_UNAUTHENTICATED, CollabRole

router = APIRouter(prefix="/collab", tags=["collab"])
Session = Annotated[AsyncSession, Depends(get_session)]


@router.post("/pages/{page_id}/join", response_model=CollabJoinRead)
async def join_page(
    page_id: uuid.UUID, data: CollabJoin, session: Session, user: CurrentUser
) -> CollabJoinRead:
    permission = (
        authz.Permission.PAGE_WRITE if data.role == CollabRole.EDITOR else authz.Permission.PAGE_READ
    )
    page = await page_access.guard_page(session, user, page_id, permission)
    collab_session, seed = await hub.join(page.id, page.version, user.id, data.role)
    return CollabJoinRead(
        session=collab_session.id, role=collab_session.role, seed=seed, page_version=page.version
    )


@router.websocket("/pages/{page_id}")
async def page_socket(
    websocket: WebSocket, page_id: uuid.UUID, session: uuid.UUID | None = None
) -> None:
    token = websocket.cookies.get(SESSION_COOKIE_NAME)
    user_id: uuid.UUID | None = None
    if token:
        async with SessionLocal() as db:
            resolved = await auth.resolve_session_users(db, token)
        if resolved is not None:
            real, target = resolved
            user_id = (target or real).id
    if token is None or user_id is None:
        # Accept-then-close so the client sees the app-level code (browsers
        # hide handshake-rejection details).
        await websocket.accept()
        await websocket.close(code=WS_CLOSE_UNAUTHENTICATED)
        return
    room = hub.room(page_id)
    collab_session = room.sessions.get(session) if (room is not None and session) else None
    if room is None or collab_session is None or collab_session.user_id != user_id:
        await websocket.accept()
        await websocket.close(code=WS_CLOSE_SESSION_UNKNOWN)
        return

    await websocket.accept()
    channel = RoomChannel(
        websocket, path=str(page_id), token=token, user_id=user_id, role=collab_session.role
    )
    room.connect(collab_session, channel)
    snapshot = room.awareness_snapshot()
    if snapshot is not None:
        await channel.send(snapshot)
    try:
        await room.yroom.serve(channel)
    finally:
        await room.disconnect(collab_session)
