"""Hot mount/unmount of a plugin into the RUNNING app (docs/plugin-platform.md §10:
enable/disable at runtime, no restart). FastAPI's router list is mutable with care —
the one subtlety is the SPA catch-all (`/{path:path}`), which must stay LAST or it
shadows freshly-added API routes. So we pop it, mount, and re-append it.
"""

import importlib

from fastapi import FastAPI

from radd.config import settings
from radd.kernel import RaddPlugin, import_models, registries
from radd.kernel import entities as kentities

_CATCHALL = "/{path:path}"


def _routers_for(plugin: RaddPlugin, path: str) -> list:
    routers = list(plugin.routers)
    if plugin.entities:
        import_models((path,))
        for spec in plugin.entities:
            kentities.register_entity(spec)
            routers.append(kentities.crud_router(spec))
    return routers


def mount_plugin(app: FastAPI, plugin: RaddPlugin, path: str) -> None:
    registries.register_plugin(plugin)
    # Record the plugin's UI bundle dir (`<plugin dir>/ui/dist`) for /plugins/<name>/* serving.
    registries.register_plugin_ui_dir(plugin, importlib.import_module(path))
    routers = _routers_for(plugin, path)
    catchall = [r for r in app.router.routes if getattr(r, "path", "") == _CATCHALL]
    for r in catchall:
        app.router.routes.remove(r)
    for router in routers:
        app.include_router(router, prefix=settings.api_prefix)
    for r in catchall:  # keep the SPA fallback last
        app.router.routes.append(r)
    app.openapi_schema = None


def unmount_plugin(app: FastAPI, plugin: RaddPlugin, path: str) -> None:
    # FastAPI's include_router no longer flattens into per-endpoint APIRoutes —
    # it appends a lazy `_IncludedRouter` wrapper whose `path` is None. The old
    # path-prefix filter therefore both MISSED every mounted router and crashed
    # on `None.startswith` (swallowed upstream), which is how a "disabled" AI
    # plugin kept serving every endpoint. Match the wrapper's `original_router`
    # instead: by identity for the plugin's own routers (module singletons at
    # boot and hot-mount alike), by prefix for entity CRUD routers (created
    # fresh per mount, but always prefixed `/{plural}`). Plain path-bearing
    # routes keep the prefix match as a fallback.
    own = set(map(id, plugin.routers))
    prefixes = {r.prefix for r in plugin.routers if getattr(r, "prefix", "")}
    prefixes.update(f"/{spec.plural or spec.key + 's'}" for spec in plugin.entities)
    path_prefixes = tuple(settings.api_prefix + p for p in prefixes)

    def belongs(route: object) -> bool:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            return id(inner) in own or getattr(inner, "prefix", "") in prefixes
        route_path = getattr(route, "path", "") or ""
        return bool(path_prefixes) and route_path.startswith(path_prefixes)

    app.router.routes = [r for r in app.router.routes if not belongs(r)]
    # Also drop the plugin's registry contributions (nav, atoms, caps, events…) so
    # /capabilities + the roles matrix stop advertising a disabled plugin.
    registries.unregister_plugin(plugin)
    app.openapi_schema = None
