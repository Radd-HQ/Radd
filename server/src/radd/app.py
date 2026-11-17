import asyncio
import secrets
from contextlib import asynccontextmanager
from enum import StrEnum
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, JSONResponse, ORJSONResponse
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeout

from radd import __version__, observability
from radd.backup import keyguard as backup_keyguard
from radd.backup import postgres as backup_postgres
from radd.config import settings
from radd.db import is_statement_timeout
from radd.exceptions import ConflictError, ForbiddenError, NotFoundError, UnauthorizedError
from radd.kernel import entities as kentities
from radd.kernel import registries
from radd.kernel import import_models, load_plugins
from radd.clientip import ClientIpMiddleware
from radd.maintenance import MaintenanceMiddleware
from radd.middleware import CommitBeforeSendMiddleware
from radd.collection_compression import CollectionCompressionMiddleware
from radd.origin_check import OriginCheckMiddleware
from radd.security_headers import SecurityHeadersMiddleware

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
        # The key that encrypts backups and stored credentials must be the one this
        # database was written with: a missing key file is a lost volume, not a first boot.
        await backup_keyguard.preflight()
        from radd.kernel import admission
        from radd.modules.pluginmgr import live
        live.bind(runtime)
        # RADD-872: no periodic tick runs until every plugin has started (a run
        # function may touch a table a later plugin's startup ensures).
        admission.gate.hold_ticks()
        loop_watch: asyncio.Task | None = None
        try:
            for plugin in plugins:
                await runtime.start_plugin(plugin)
            admission.gate.release_ticks()
            await live.start()
            loop_watch = asyncio.create_task(observability.watch_event_loop())
            yield
        finally:
            if loop_watch is not None:
                loop_watch.cancel()
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

    @app.get("/metrics", include_in_schema=False)
    async def metrics_endpoint(request: Request) -> Response:
        """Prometheus scrape target (RADD-1530). Absent unless enabled, so a public
        instance does not publish its routes and traffic by default."""
        if not settings.metrics_enabled:
            raise HTTPException(status_code=404)
        if settings.metrics_token:
            sent = request.headers.get("authorization", "")
            if not secrets.compare_digest(sent, f"Bearer {settings.metrics_token}"):
                raise HTTPException(status_code=401)
        body = observability.render_metrics(await observability.live_metrics())
        return Response(body, media_type="text/plain; version=0.0.4; charset=utf-8")

    @app.get("/ready", include_in_schema=False)
    async def ready() -> JSONResponse:
        """Readiness (RADD-1534): can this process serve a request RIGHT NOW? Unlike
        /health it asks the database, so an orchestrator stops routing to a pod that
        cannot reach it. Never use it for liveness: restarting the pod does not bring
        a database back, and a restart loop would hide which of the two is down."""

        from sqlalchemy import text

        from radd.db import engine

        async def ask() -> None:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))

        try:
            await asyncio.wait_for(ask(), timeout=settings.readiness_timeout_seconds)
        except Exception as error:  # noqa: BLE001 — any failure to answer is "not ready"
            return JSONResponse(
                status_code=503,
                content={"status": HealthStatus.DEGRADED, "database": type(error).__name__},
            )
        return JSONResponse(content={"status": HealthStatus.OK, "version": __version__})

    app.add_middleware(CommitBeforeSendMiddleware)
    app.add_middleware(CollectionCompressionMiddleware)
    # nosniff, frame protection, referrer policy, HSTS over https, and the CSP (RADD-1531).
    app.add_middleware(SecurityHeadersMiddleware)
    # A cookie-authenticated write or socket must come from this instance (RADD-1547).
    app.add_middleware(OriginCheckMiddleware)
    # Resolves the client IP (trusted-proxy XFF walk) into request.state.client_ip.
    app.add_middleware(ClientIpMiddleware)
    # Outermost: while a restore is replacing the database, everything but the
    # backup status/run endpoints answers 503 (radd/maintenance.py).
    app.add_middleware(MaintenanceMiddleware)
    # Outermost of all (RADD-1530): the request ID exists before anything logs, and
    # the latency it records includes every other middleware.
    app.add_middleware(observability.ObservabilityMiddleware)
    observability.configure_logging()

    for error, status_code in (
        (NotFoundError, 404), (ConflictError, 409), (UnauthorizedError, 401), (ForbiddenError, 403)
    ):
        app.add_exception_handler(error, _detail_handler(status_code))
    app.add_exception_handler(DBAPIError, _database_error_handler)
    app.add_exception_handler(PoolTimeout, _pool_exhausted_handler)

    from radd.kernel.runtime import PluginRuntime, RuntimeMiddleware
    runtime = PluginRuntime(app)
    # Reachable for tooling and tests (RADD-1466): the lifespan binds it to the reconciler at
    # startup; a test that applies a plugin state change without the lifespan binds it itself.
    app.state.plugin_runtime = runtime
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


async def _database_error_handler(request: Request, exc: DBAPIError) -> JSONResponse:
    """A statement cancelled for running past the request limit (RADD-1532) is a 504
    that says so, not an anonymous 500. Every other database error is re-raised."""
    if not is_statement_timeout(exc):
        raise exc
    return JSONResponse(
        status_code=504,
        content={
            "detail": (
                "this request's query ran longer than "
                f"{settings.db_statement_timeout_seconds} seconds and was stopped — "
                "narrow the search or the date range and try again"
            )
        },
    )


async def _pool_exhausted_handler(request: Request, exc: Exception) -> JSONResponse:
    """No database connection came free within `db_pool_timeout_seconds`: the
    instance is over capacity, which is a 503 a client may retry — the load test
    (RADD-1536) got these as anonymous 500s, indistinguishable from a bug."""
    return JSONResponse(
        status_code=503,
        headers={"Retry-After": "5"},
        content={"detail": "the server is busy — every database connection is in use; try again shortly"},
    )


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

    # An unknown API path must 404 for EVERY method, never serve the SPA shell: a disabled
    # plugin's endpoints have to look ABSENT (the spec-46 dormant convention), and a 200
    # text/html "response" masks real client bugs. This used to be a check inside the GET-only
    # catch-all below, so a POST to a withdrawn plugin route answered 405 (RADD-1466).
    @app.api_route(
        f"{settings.api_prefix.rstrip('/')}/{{path:path}}",
        methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        include_in_schema=False,
    )
    async def absent_api_path(path: str) -> None:
        raise HTTPException(status_code=404)

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        candidate = (web_dist / path).resolve()
        if candidate.is_file() and candidate.is_relative_to(web_dist.resolve()):
            # Hashed build assets are immutable; the /shared shims + everything else revalidate so a
            # rebuild is picked up on reload.
            headers = _IMMUTABLE if path.startswith("assets/") else _REVALIDATE
            return FileResponse(candidate, headers=headers)
        # A missing build asset is ABSENT, never the shell (RADD-1527). Every release
        # replaces the bundle, so a tab opened before it asks for the old hash on its
        # next lazy route: answered with index.html and a 200 it failed to parse as a
        # module and stranded the user; a 404 is what lets the SPA notice and reload.
        if path.startswith("assets/"):
            raise HTTPException(status_code=404)
        # index.html (the SPA shell) must always revalidate — it references the current asset hashes.
        return FileResponse(index, headers=_REVALIDATE)
