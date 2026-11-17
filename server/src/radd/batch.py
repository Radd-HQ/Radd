"""Several reads in one request (RADD-1561).

An issue page asks about fifteen small questions about one item — its watchers,
participants, SLA, approvals, links, time, and so on — each a request of its
own, because each section (most of them plugins) owns its endpoint. That
independence is worth keeping; the fifteen round trips are not.

`POST {api}/batch` takes a list of GET paths and answers each one, by running
it through this same application: the same routes, the same authorization, the
same middleware, with the caller's own credentials. Nothing is special-cased
and no plugin knows it exists — a section that is batched and one that is not
return the same bytes.

Rejected: a "panels" endpoint each plugin contributes a section to. It would
save the same round trips at the cost of a second way to read every section,
kept in step by hand, and a core route that knows which plugins exist.

Only GETs, only under the API prefix, never itself, and at most
`batch_max_requests` at a time. A caller gets nothing through here that the
same GET would not have given them.
"""

from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from radd.config import settings

#: Sub-requests run a few at a time: each takes a database connection, and a
#: batch must not empty the pool for everyone else.
CONCURRENCY = 3
#: The caller's headers a sub-request carries. Not Accept-Encoding: the batch
#: response is compressed once, as a whole.
_FORWARDED = (b"cookie", b"authorization", b"x-forwarded-for", b"x-request-id", b"user-agent")
BATCH_PATH = "/batch"


async def _one(request: Request, path: str) -> tuple[int, bytes | None]:
    parts = urlsplit(path)
    full = settings.api_prefix.rstrip("/") + parts.path
    headers = [(name, value) for name, value in request.scope["headers"] if name in _FORWARDED]
    scope = {
        **request.scope,
        "method": "GET",
        "path": full,
        "raw_path": full.encode(),
        "query_string": parts.query.encode(),
        "headers": headers,
        # A fresh per-request state: the session and its memo belong to one request.
        "state": {},
    }
    scope.pop("route", None)
    scope.pop("endpoint", None)
    scope.pop("path_params", None)
    status = 500
    content_type = b""
    chunks: list[bytes] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        nonlocal status, content_type
        if message["type"] == "http.response.start":
            status = message["status"]
            content_type = dict(message.get("headers") or ()).get(b"content-type", b"")
        elif message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))

    await request.app(scope, receive, send)
    body = b"".join(chunks)
    if not body:
        return status, None
    if not content_type.startswith(b"application/json"):
        return 415, b'{"detail":"only JSON responses can be batched"}'
    return status, body


def _refusal(paths: object) -> str | None:
    if not isinstance(paths, list) or not paths:
        return "requests must be a non-empty list of paths"
    if len(paths) > settings.batch_max_requests:
        return f"at most {settings.batch_max_requests} requests in one batch"
    for path in paths:
        if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
            return "each request is a path under the API, starting with /"
        parts = urlsplit(path)
        if parts.scheme or parts.netloc or ".." in parts.path.split("/"):
            return "each request is a path under the API, starting with /"
        if parts.path.rstrip("/") == BATCH_PATH:
            return "a batch cannot contain a batch"
    return None


async def batch(request: Request) -> Response:
    try:
        paths = (await request.json()).get("requests")
    except Exception:  # noqa: BLE001 — any unreadable body is the same refusal
        return JSONResponse(status_code=422, content={"detail": "the body must be JSON"})
    refusal = _refusal(paths)
    if refusal:
        return JSONResponse(status_code=422, content={"detail": refusal})
    gate = asyncio.Semaphore(CONCURRENCY)

    async def run(path: str) -> tuple[int, bytes | None]:
        async with gate:
            return await _one(request, path)

    results = await asyncio.gather(*(run(path) for path in paths))
    # Each body is already JSON: it is spliced in as it came, not parsed and
    # written again.
    parts = [
        b'{"status":%d,"body":%s}' % (status, body if body is not None else b"null")
        for status, body in results
    ]
    return Response(b"[" + b",".join(parts) + b"]", media_type="application/json")
