from contextlib import asynccontextmanager
from enum import StrEnum
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, JSONResponse, ORJSONResponse

from radd import __version__
from radd.backup import postgres as backup_postgres
from radd.config import settings
from radd.exceptions import ConflictError, ForbiddenError, NotFoundError, UnauthorizedError
from radd.kernel import entities as kentities
from radd.kernel import registries
from radd.kernel import import_models, load_plugins
from radd.clientip import ClientIpMiddleware
from radd.maintenance import MaintenanceMiddleware
from radd.middleware import CommitBeforeSendMiddleware
from radd.collection_compression import CollectionCompressionMiddleware

# Repo-layout fallback for the built SPA; harmless when absent (API-only mode).
_DEFAULT_WEB_DIST = Path(__file__).resolve().parents[3] / "web" / "dist"


class HealthStatus(StrEnum):
    OK = "ok"
    #: Serving, but this process's plugin lease lapsed (its heartbeat cannot
    #: reach the database): non-core plugin routes answer 503 until it renews.
    DEGRADED = "degraded"


def create_app() -> FastAPI:
    # Boot set (docs/plugin-platform.md §10): core bootstrap plugins always; optional
    # bootstrap plugins unless explicitly disabled; installable plugins when enabled.
    # Resolved synchronously (behaves as "no overrides" before the table exists).
    from radd.modules.pluginmgr.boot import resolve_boot_paths

    plugin_paths = resolve_boot_paths()
    import_models(plugin_paths)
    plugins = load_plugins(plugin_paths)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Create any declaratively-registered plugin entity tables (idempotent) —
        # the "install" step for entities without a dedicated migration (§5).
        await kentities.ensure_tables()
        # pg_dump/pg_restore are runtime requirements, not optional capabilities:
        # a backup system that silently cannot back up is worse than one that
        # refuses to start (RADD_BACKUP_TOOLS_OPTIONAL downgrades this to a warning).
        await backup_postgres.preflight()
        from radd.kernel import admission
        from radd.modules.pluginmgr import live
        live.bind(runtime)
        # RADD-872: no periodic tick runs until every plugin has started (a run
        # function may touch a table a later plugin's startup ensures).
        admission.gate.hold_ticks()
        try:
            for plugin in plugins:
                await runtime.start_plugin(plugin)
            admission.gate.release_ticks()
            await live.start()
            yield
        finally:
            # RADD-1372: each step guarded so none skips the next — the reconciler stops
            # first (nothing enables a plugin mid-shutdown), then every on_shutdown (collab
            # flushes its rooms), then this process's acknowledgement is withdrawn.
            admission.gate.release_ticks()
            await live.halt()
            try:
                await runtime.shutdown()
            finally:
                await live.withdraw()

    # orjson for every route response (RADD-1067): jsonable_encoder has already reduced
    # everything to primitives, so the swap changes speed, not shape.
    app = FastAPI(
        title=settings.api_title,
        version=__version__,
        lifespan=lifespan,
        default_response_class=ORJSONResponse,
    )

    @app.get("/health", include_in_schema=False)
    async def health() -> dict[str, str]:
        # Unprefixed liveness probe (RADD-870). Reports the plugin lease but stays 200: a
        # lapsed lease means the DB is unreachable, and a restart would not help (RADD-1372).
        from radd.kernel import admission

        lease = admission.gate.lease_state()
        lapsed = lease is admission.LeaseState.LAPSED
        status = HealthStatus.DEGRADED if lapsed else HealthStatus.OK
        return {"status": status, "version": __version__, "plugin_lease": lease}

    app.add_middleware(CommitBeforeSendMiddleware)
    app.add_middleware(CollectionCompressionMiddleware)
    # Resolves the client IP (trusted-proxy XFF walk) into request.state.client_ip.
    app.add_middleware(ClientIpMiddleware)
    # Outermost: while a restore is replacing the database, everything but the
    # backup status/run endpoints answers 503 (radd/maintenance.py).
    app.add_middleware(MaintenanceMiddleware)

    for error, status_code in (
        (NotFoundError, 404), (ConflictError, 409), (UnauthorizedError, 401), (ForbiddenError, 403)
    ):
        app.add_exception_handler(error, _detail_handler(status_code))

    from radd.kernel.runtime import PluginRuntime, RuntimeMiddleware
    runtime = PluginRuntime(app)
    app.add_middleware(RuntimeMiddleware)
    for plugin in plugins:
        runtime.mount(plugin)

    def openapi_with_augmentors() -> dict[str, Any]:
        # Rebuilt per call so registry-driven schema (custom fields) is always live.
        schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
        for plugin in list(registries.plugins.values()):
            for augment in plugin.openapi_augmentors:
                augment(schema)
        return schema

    app.openapi = openapi_with_augmentors  # type: ignore[method-assign]

    _mount_plugin_assets(app)
    _mount_spa(app)
    return app


def _detail_handler(status_code: int):
    async def handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status_code, content={"detail": str(exc)})

    return handler


# STABLE-url files (plugin bundles, /shared shims, index.html) change on rebuild, so they are
# REVALIDATED each load (`no-cache` → ETag 304 or fresh 200), or a reload shows a stale build.
_REVALIDATE = {"Cache-Control": "no-cache"}
# Content-hashed build assets (vite emits new filenames on change) are safe to cache forever.
_IMMUTABLE = {"Cache-Control": "public, max-age=31536000, immutable"}


def _mount_plugin_assets(app: FastAPI) -> None:
    """Serve each plugin's UI federation bundle at /plugins/<name>/… from the plugin's OWN directory
    (`<plugin dir>/ui/dist`, recorded in `registries.plugin_ui_dirs`) — a plugin's UI lives with the
    plugin, builtin or external (spec 94). Registered before the SPA catch-all so a bundle is served
    as a real file, not the SPA index. Served `no-cache` (stable url, rebuilt in place)."""

    @app.get("/plugins/{name}/{file:path}", include_in_schema=False)
    async def plugin_asset(name: str, file: str) -> FileResponse:
        base = registries.plugin_ui_dirs.get(name)
        if base:
            root = Path(base).resolve()
            candidate = (root / file).resolve()
            if candidate.is_file() and candidate.is_relative_to(root):
                # Ensure ESM bundles get a JS media type regardless of the platform mimetypes db.
                media = "text/javascript" if candidate.suffix in (".js", ".mjs") else None
                return FileResponse(candidate, media_type=media, headers=_REVALIDATE)
        raise NotFoundError("plugin asset", f"{name}/{file}")


def _mount_spa(app: FastAPI) -> None:
    """Serve the built web UI (if present) with SPA fallback — registered after all API routes."""
    web_dist = Path(settings.web_dist) if settings.web_dist else _DEFAULT_WEB_DIST
    index = web_dist / "index.html"
    if not index.is_file():
        return

    api_root = settings.api_prefix.lstrip("/") + "/"

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        # An unknown API path must 404, never serve the SPA shell: a disabled
        # plugin's endpoints have to look ABSENT (the spec-46 dormant
        # convention), and a 200 text/html "response" masks real client bugs.
        if path.startswith(api_root):
            raise HTTPException(status_code=404)
        candidate = (web_dist / path).resolve()
        if candidate.is_file() and candidate.is_relative_to(web_dist.resolve()):
            # Hashed build assets are immutable; the /shared shims + everything else revalidate so a
            # rebuild is picked up on reload.
            headers = _IMMUTABLE if path.startswith("assets/") else _REVALIDATE
            return FileResponse(candidate, headers=headers)
        # index.html (the SPA shell) must always revalidate — it references the current asset hashes.
        return FileResponse(index, headers=_REVALIDATE)
