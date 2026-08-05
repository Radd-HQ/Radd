"""ASGI middleware that holds a response until the request's transaction has committed.

FastAPI runs dependency-with-yield teardown (where `get_session` commits) AFTER the
response bytes are sent. A client that reads its response and immediately issues a
dependent request can therefore miss the write (found in the wild by the Jira importer).
Buffering the send until the inner app — including that teardown — finishes closes the
race. Non-http scopes (websockets, lifespan) pass through untouched.

Two response shapes bypass the buffer (RADD-877): event streams (buffering defeats
them) and file deliveries (buffering holds the entire artifact in RAM — a multi-GB
backup download accumulated in a Python list before the first byte left). Both are
recognized from the response-start headers, and neither is ever the JSON API answer
the commit race involves: a download commits nothing a follow-up request depends on.
"""

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
