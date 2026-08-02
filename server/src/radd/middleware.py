"""ASGI middleware that holds a response until the request's transaction has committed.

FastAPI runs dependency-with-yield teardown (where `get_session` commits) AFTER the
response bytes are sent. A client that reads its response and immediately issues a
dependent request can therefore miss the write (found in the wild by the Jira importer).
Buffering the send until the inner app — including that teardown — finishes closes the
race. Non-http scopes (websockets, lifespan) pass through untouched.
"""

from collections.abc import Awaitable, Callable
from typing import Any

Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Any, Receive, Send], Awaitable[None]]


_EVENT_STREAM = b"text/event-stream"


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
            # SSE responses (spec 103 editor streaming) must NOT be held back —
            # buffering a stream until the app finishes defeats it entirely. The
            # commit race this middleware closes doesn't apply: a stream commits
            # nothing a follow-up request depends on. Flush and pass through the
            # moment an event-stream response starts.
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers") or ())
                if headers.get(b"content-type", b"").startswith(_EVENT_STREAM):
                    streaming = True
                    for held in buffered:
                        await send(held)
                    buffered.clear()

        await self.app(scope, receive, buffer)
        for message in buffered:
            await send(message)
