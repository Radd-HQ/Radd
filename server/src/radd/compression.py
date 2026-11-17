"""Compress what the server sends (RADD-1549).

Until this only `/items` and `/items/grouped` were compressed, on the assumption
that a proxy in front handles the rest. Measured on the live instance, behind
its proxy: the main script left as 270 KB of plain text, and a cold page load
moved about 2.0 MB of JavaScript that compresses to a third. `/labels` was
279 KB and `/fields` 150 KB on every issue page.

A GET response is gzipped when the client accepts it, its content type is text
(JSON, JavaScript, CSS, HTML, SVG), it is at least `MINIMUM_BYTES`, and nothing
has encoded it already. Left alone, on purpose:

- **auth and token routes** — a response that can hold a secret is not
  compressed next to anything a caller can influence;
- **attachments and backups** — files, mostly compressed already, and a
  download keeps its length;
- **event streams** — compressing a stream holds its messages back;
- **everything that is not a GET.**

**Built assets are compressed once.** A hashed file under `/assets/` never
changes, so its compressed form is kept in memory (bounded) and later requests
are answered from it without reading the file or running gzip again.
"""

from __future__ import annotations

import zlib
from collections import OrderedDict

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from radd.config import settings

MINIMUM_BYTES = 1024
#: Fast and nearly as small as the slower levels on JSON and script.
LEVEL = 5
#: Hashed build assets are compressed harder: once, then served from memory.
ASSET_LEVEL = 9
ASSET_PREFIX = "/assets/"
ASSET_CACHE_BYTES = 48 * 1024 * 1024

_COMPRESSIBLE = (
    "application/json",
    "application/javascript",
    "text/javascript",
    "text/css",
    "text/html",
    "text/plain",
    "image/svg+xml",
    "application/manifest+json",
)
#: API path prefixes whose responses are never compressed (see the module docstring).
_EXCLUDED_API = ("/auth", "/tokens", "/attachments", "/backups")


def _excluded(path: str) -> bool:
    prefix = settings.api_prefix.rstrip("/")
    if not path.startswith(prefix + "/"):
        return False
    rest = path[len(prefix):]
    return any(rest == part or rest.startswith(part + "/") for part in _EXCLUDED_API)


class _AssetCache:
    """Compressed bodies of immutable assets, least recently used first out."""

    def __init__(self) -> None:
        self.entries: OrderedDict[str, tuple[list[tuple[bytes, bytes]], bytes]] = OrderedDict()
        self.size = 0

    def get(self, path: str) -> tuple[list[tuple[bytes, bytes]], bytes] | None:
        hit = self.entries.get(path)
        if hit is not None:
            self.entries.move_to_end(path)
        return hit

    def put(self, path: str, headers: list[tuple[bytes, bytes]], body: bytes) -> None:
        if len(body) > ASSET_CACHE_BYTES // 4 or path in self.entries:
            return
        self.entries[path] = (headers, body)
        self.size += len(body)
        while self.size > ASSET_CACHE_BYTES:
            _, (_, evicted) = self.entries.popitem(last=False)
            self.size -= len(evicted)


assets = _AssetCache()


class CompressionMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") != "GET":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        accepts = "gzip" in Headers(scope=scope).get("accept-encoding", "")
        if not accepts or _excluded(path):
            await self.app(scope, receive, send)
            return
        cached = assets.get(path) if path.startswith(ASSET_PREFIX) else None
        if cached is not None:
            headers, body = cached
            await send({"type": "http.response.start", "status": 200, "headers": headers})
            await send({"type": "http.response.body", "body": body})
            return
        await _Responder(self.app, path)(scope, receive, send)


class _Responder:
    """Holds the response start until the first body chunk says whether the body
    is worth compressing, then streams it through one gzip stream."""

    def __init__(self, app: ASGIApp, path: str) -> None:
        self.app = app
        self.path = path
        self.start: Message | None = None
        self.compressor: zlib._Compress | None = None
        self.passthrough = False
        #: Set while an immutable asset's compressed body is being collected.
        self.collecting: list[bytes] | None = None
        self.headers: list[tuple[bytes, bytes]] = []

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.send = send
        await self.app(scope, receive, self.on_message)

    def _worth_it(self, headers: Headers, first: bytes, more: bool) -> bool:
        if self.start["status"] != 200 or "content-encoding" in headers:
            return False
        content_type = headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type not in _COMPRESSIBLE:
            return False
        declared = headers.get("content-length")
        size = int(declared) if declared and declared.isdigit() else len(first)
        return size >= MINIMUM_BYTES or (more and declared is None)

    async def on_message(self, message: Message) -> None:
        if message["type"] == "http.response.start":
            self.start = message
            return
        if message["type"] != "http.response.body" or self.passthrough:
            await self.send(message)
            return
        body = message.get("body", b"")
        more = message.get("more_body", False)
        if self.compressor is None:
            headers = Headers(raw=self.start["headers"])
            if not self._worth_it(headers, body, more):
                self.passthrough = True
                await self.send(self.start)
                await self.send(message)
                return
            immutable = self.path.startswith(ASSET_PREFIX) and "immutable" in headers.get(
                "cache-control", ""
            )
            self.compressor = zlib.compressobj(ASSET_LEVEL if immutable else LEVEL, wbits=31)
            mutable = MutableHeaders(raw=list(self.start["headers"]))
            mutable["Content-Encoding"] = "gzip"
            mutable.add_vary_header("Accept-Encoding")
            del mutable["Content-Length"]
            if immutable:
                self.collecting = []
                self.headers = mutable.raw
            else:
                await self.send({**self.start, "headers": mutable.raw})
        chunk = self.compressor.compress(body)
        if not more:
            chunk += self.compressor.flush()
        if self.collecting is not None:
            # An immutable asset: sent whole, with its length, and kept for next time.
            self.collecting.append(chunk)
            if more:
                return
            whole = b"".join(self.collecting)
            headers = [*self.headers, (b"content-length", str(len(whole)).encode())]
            assets.put(self.path, headers, whole)
            await self.send({**self.start, "headers": headers})
            await self.send({"type": "http.response.body", "body": whole})
            return
        await self.send({"type": "http.response.body", "body": chunk, "more_body": more})
