"""Hold a response until the request's transaction has committed: FastAPI runs the
committing `get_session` teardown AFTER the response is sent, so a client's immediate
follow-up could miss the write. Non-http scopes pass through. SSE and Content-Disposition
responses stream through (RADD-877) — buffering a multi-GB download holds it in RAM, and
neither commits anything a follow-up depends on."""

from collections.abc import Awaitable, Callable
from typing import Any

Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Any, Receive, Send], Awaitable[None]]


_EVENT_STREAM = b"text/event-stream"


def _flush_through(message: Message) -> bool:
    """True for responses that must stream instead of buffer: SSE (spec 103) and
    anything carrying Content-Disposition — every file-serving path (backup
    download, attachment proxy/thumbnail, page PDF) sets one, and no JSON API
    response does."""
    headers = dict(message.get("headers") or ())
    if headers.get(b"content-type", b"").startswith(_EVENT_STREAM):
        return True
    return b"content-disposition" in headers


class CommitBeforeSendMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Any, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        buffered: list[Message] = []
        streaming = False

        async def buffer(message: Message) -> None:
            nonlocal streaming
            if streaming:
                await send(message)
                return
            buffered.append(message)
            if message["type"] == "http.response.start" and _flush_through(message):
                streaming = True
                for held in buffered:
                    await send(held)
                buffered.clear()

        await self.app(scope, receive, buffer)
        for message in buffered:
            await send(message)
