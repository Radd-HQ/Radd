import asyncio
import json

from radd.config import settings
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from radd.db import SessionLocal
from radd.modules.auth import service as auth
from radd.modules.auth import authz
from radd.modules.auth.types import SESSION_COOKIE_NAME

from .hub import ClientInfo, hub, validate_subscriptions, authorize_item_subscriptions
from .types import WS_CLOSE_UNAUTHENTICATED

router = APIRouter(tags=["realtime"])


@router.websocket("/ws")
async def realtime_socket(websocket: WebSocket) -> None:
    """Authenticated invalidation stream. Clients may subscribe active query
    identities and explicit project scopes; scope validation uses ordinary RBAC.
    No record content or server-side record identifiers are published."""
    token = websocket.cookies.get(SESSION_COOKIE_NAME)
    info: ClientInfo | None = None
    if token:
        async with SessionLocal() as session:
            resolved = await auth.resolve_session_users(session, token)
            if resolved is not None:
                real, target = resolved
                user = target or real
                info = ClientInfo(user_id=user.id)
    if info is None:
        # Accept-then-close so the client sees the app-level code (browsers hide
        # handshake-rejection details).
        await websocket.accept()
        await websocket.close(code=WS_CLOSE_UNAUTHENTICATED)
        return

    await websocket.accept()
    hub.register(websocket, info)
    try:
        while True:
            # The deadline is absolute: inbound traffic cannot extend a revoked session.
            try:
                async with asyncio.timeout(settings.realtime_session_refresh_seconds):
                    while True:
                        body = await websocket.receive_text()
                        if len(body) > 262144:
                            raise ValueError("realtime subscription frame too large")
                        data = json.loads(body)
                        async with SessionLocal() as session:
                            resolved = await auth.resolve_session_users(session, token)
                            current = (resolved[1] or resolved[0]) if resolved else None
                            if current is None or current.id != info.user_id:
                                await websocket.close(code=WS_CLOSE_UNAUTHENTICATED)
                                return
                            readable = await authz.readable_projects(session, current)
                            info.subscriptions = await authorize_item_subscriptions(
                                session, current, validate_subscriptions(
                                    data.get("queries"), set(map(str, readable))
                                )
                            )
            except TimeoutError:
                async with SessionLocal() as session:
                    resolved = await auth.resolve_session_users(session, token)
                    user = (resolved[1] or resolved[0]) if resolved else None
                    if user is None or user.id != info.user_id:
                        await websocket.close(code=WS_CLOSE_UNAUTHENTICATED)
                        break
                    if info.subscriptions is not None:
                        readable = await authz.readable_projects(session, user)
                        info.subscriptions = await authorize_item_subscriptions(
                            session, user, validate_subscriptions(
                                info.subscriptions, set(map(str, readable))
                            )
                        )
    except (ValueError, TypeError, AttributeError):
        await websocket.close(code=1008)
    except WebSocketDisconnect:
        pass
    finally:
        hub.unregister(websocket)
