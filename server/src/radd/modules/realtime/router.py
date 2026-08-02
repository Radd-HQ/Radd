from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from radd.db import SessionLocal
from radd.modules.auth import service as auth
from radd.modules.auth.types import SESSION_COOKIE_NAME

from .hub import ClientInfo, hub
from .types import WS_CLOSE_UNAUTHENTICATED

router = APIRouter(tags=["realtime"])


@router.websocket("/ws")
async def realtime_socket(websocket: WebSocket) -> None:
    """Live update stream. Auth = the same session cookie as REST (spec 86:
    authenticated = subscribed; no membership snapshot). The client never needs
    to send anything — inbound messages are drained and ignored."""
    token = websocket.cookies.get(SESSION_COOKIE_NAME)
    info: ClientInfo | None = None
    if token:
        async with SessionLocal() as session:
            user = await auth.user_for_session_token(session, token)
            if user is not None:
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
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        hub.unregister(websocket)
