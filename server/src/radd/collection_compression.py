"""Compress bounded issue collection JSON without changing its response contract.

The allowlist excludes auth, files, event streams and mutation responses. Existing
proxy compression is respected by Starlette's Content-Encoding guard.
"""
from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send


class CollectionCompressionMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.compressed = GZipMiddleware(app, minimum_size=2048, compresslevel=3)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        compress = scope["type"] == "http" and scope.get("method") == "GET" and scope.get("path") in {
            "/api/v1/items", "/api/v1/items/grouped", "/api/v1/sla-queue-items",
        }
        await (self.compressed if compress else self.app)(scope, receive, send)
