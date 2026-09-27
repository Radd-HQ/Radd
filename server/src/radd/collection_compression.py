"""Compress bounded issue collection JSON without changing its response contract.

The allowlist excludes auth, files, event streams and mutation responses. Existing
proxy compression is respected by Starlette's Content-Encoding guard.
"""
from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from radd.config import settings
from radd.kernel.registry import registries

#: The host list's own collections, relative to the API root (`items` is core).
CORE_COLLECTION_PATHS = ("/items", "/items/grouped")


def collection_paths() -> frozenset[str]:
    """Every compressible collection: the core ones plus the rows endpoint of each
    list-surface view type a LOADED plugin registers, so a disabled plugin's path
    leaves with it and core never names an optional plugin's route."""
    contributed = (
        spec.list_surface.rows_path
        for spec in registries.view_types.values()
        if spec.list_surface is not None and spec.list_surface.rows_path
    )
    return frozenset(settings.api_prefix + path for path in (*CORE_COLLECTION_PATHS, *contributed))


class CollectionCompressionMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.compressed = GZipMiddleware(app, minimum_size=2048, compresslevel=3)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        compress = (
            scope["type"] == "http"
            and scope.get("method") == "GET"
            and scope.get("path") in collection_paths()
        )
        await (self.compressed if compress else self.app)(scope, receive, send)
