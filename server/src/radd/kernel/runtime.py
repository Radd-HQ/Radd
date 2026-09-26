"""A process's plugin routes, hooks and scheduled loops, swapped at safe points.

Enable and disable change ONE plugin at a time, after that plugin's own admitted
work has drained (`kernel.admission`, RADD-1372). Every other plugin keeps
serving and ticking while it happens.

- **enable** closes the plugin, registers and mounts it, starts it, then opens
  it: its routes and ticks admit nothing until its startup has finished.
- **disable** closes the plugin and keeps it closed until it is enabled again.
  A drain that times out, or a shutdown hook that fails, leaves it registered
  and closed for the reconciler to retry; reopening in between would admit the
  very work that keeps the drain from finishing. `resume` cancels a pending
  disable.
- **shutdown** stops every started plugin, and one plugin's failure never skips
  another's hooks.
"""

import importlib
import logging
from dataclasses import fields

from . import admission
from .admission import RuntimeGate, RuntimeMiddleware, owner, spawn

__all__ = ["PluginRuntime", "RuntimeGate", "RuntimeMiddleware", "owner", "spawn"]

logger = logging.getLogger(__name__)


def schedule_tasks(plugin, backend=None) -> list:
    """RADD-872: the loops for every periodic TaskSpec a plugin declares.

    Enqueue-only specs (interval=None) have no tick to schedule. A spec without
    its own gate runs under the spec-48 worker split like every hand-rolled loop."""
    from radd.config import settings

    from .sockets import Socket, provider

    periodic = [spec for spec in plugin.tasks if spec.interval is not None]
    if not periodic:
        return []
    backend = backend or provider(Socket.TASK_BACKEND, settings.task_backend)
    if backend is None:
        raise RuntimeError("No task backend is available")
    return [
        backend.schedule(spec.name, spec.run, spec.interval,
                         gate=spec.gate or (lambda: settings.run_workers))
        for spec in periodic
    ]


class PluginRuntime:
    """Owns routes, hooks, and scheduled loops for this application process."""

    def __init__(self, app):
        self.app = app
        self.routes: dict[str, list] = {}
        self.loops: dict[str, list] = {}
        self.started: list = []
        #: Plugins whose shutdown began but did not finish (a hook raised).
        self.stopping: set[str] = set()
        self.base_handlers = dict(app.exception_handlers)

    def mount(self, plugin):
        from fastapi import Depends

        from radd.config import settings

        from . import entities

        start = len(self.app.routes)
        owned = [Depends(admission.admission(plugin.id))]
        for router in plugin.routers:
            self.app.include_router(router, prefix=settings.api_prefix, dependencies=owned)
        for spec in plugin.entities:
            entities.register_entity(spec)
            self.app.include_router(entities.crud_router(spec), prefix=settings.api_prefix,
                                    dependencies=owned)
        added = self.app.routes[start:]
        del self.app.routes[start:]
        # API routes precede the plugin-assets/SPA fallback, including late enables.
        index = getattr(self, "route_end", len(self.app.routes))
        self.app.routes[index:index] = added
        self.route_end = index + len(added)
        self.routes[plugin.id] = added
        self.refresh_routes()
        for exc_type, handler in plugin.exception_handlers:
            self.app.exception_handlers[exc_type] = handler
        self.refresh_handlers()

    def refresh_routes(self):
        self.app.router._mark_routes_changed()
        self.app.openapi_schema = None

    def refresh_handlers(self):
        # Starlette copies handlers when building its middleware stack. Update
        # that existing ExceptionMiddleware as well as the app's declarations.
        from starlette.middleware.exceptions import ExceptionMiddleware

        node = self.app.middleware_stack
        while node is not None:
            if isinstance(node, ExceptionMiddleware):
                node._exception_handlers = {**ExceptionMiddleware(self.app)._exception_handlers,
                                            **self.app.exception_handlers}
                break
            node = getattr(node, "app", None)

    async def start_plugin(self, plugin):
        # The owner is copied into every task started here, so a loop's ticks
        # and a hook's spawned jobs are counted against this plugin.
        token = owner.set(plugin.id)
        self.loops.setdefault(plugin.id, [])
        try:
            for hook in plugin.on_startup:
                await hook()
            for loop in schedule_tasks(plugin):
                self.loops[plugin.id].append(loop)
                await loop.start()
            self.started.append(plugin)
        finally:
            owner.reset(token)

    async def stop_plugin(self, plugin):
        self.stopping.add(plugin.id)
        token = owner.set(plugin.id)
        try:
            for loop in reversed(self.loops.get(plugin.id, [])):
                await loop.stop()
            for hook in plugin.on_shutdown:
                await hook()
        finally:
            owner.reset(token)
        self.loops.pop(plugin.id, None)
        self.started[:] = [p for p in self.started if p.id != plugin.id]
        self.stopping.discard(plugin.id)

    def unmount(self, plugin):
        owned = {id(r) for r in self.routes.pop(plugin.id, [])}
        self.app.routes[:] = [r for r in self.app.routes if id(r) not in owned]
        self.route_end -= len(owned)
        self.refresh_routes()
        from .registry import registries

        self.app.exception_handlers = dict(self.base_handlers)
        for remaining in registries.plugins.values():
            for exc_type, handler in remaining.exception_handlers:
                self.app.exception_handlers[exc_type] = handler
        self.refresh_handlers()

    async def enable(self, plugin, path):
        from . import entities
        from .loader import _check_subjects
        from .registry import registries

        gate = admission.gate
        gate.close(plugin.id)  # routes mount below; nothing is admitted until it has started
        try:
            await gate.drain(plugin.id)
            snapshot = {f.name: getattr(registries, f.name).copy() for f in fields(registries)}
            registries.register_plugin(plugin)
            try:
                registries.register_plugin_ui_dir(plugin, importlib.import_module(path))
                self.mount(plugin)
                _check_subjects(list(registries.plugins.values()))
                await entities.ensure_tables()
                await self.start_plugin(plugin)
            except BaseException:
                try:
                    await self.stop_plugin(plugin)
                finally:
                    for name, value in snapshot.items():
                        target = getattr(registries, name)
                        target.clear()
                        target.extend(value) if isinstance(target, list) else target.update(value)
                    self.unmount(plugin)
                raise
        finally:
            gate.open(plugin.id)

    async def disable(self, plugin):
        from .registry import registries

        gate = admission.gate
        gate.close(plugin.id)  # stays closed until enabled again (module docstring)
        await gate.drain(plugin.id)
        await gate.close_sockets(plugin.id)
        await self.stop_plugin(plugin)
        registries.unregister_plugin(plugin)
        self.unmount(plugin)

    async def resume(self, plugin):
        """Cancel a pending disable of a still-registered plugin: restart it if
        its shutdown had begun, then reopen its admissions."""
        if plugin.id in self.stopping:
            await self.stop_plugin(plugin)
            await self.start_plugin(plugin)
        admission.gate.open(plugin.id)

    async def shutdown(self):
        """Stop every started plugin, dependents first. A failing hook is logged
        and never skips another plugin's (collab's flush must always run)."""
        for plugin in reversed(list(self.started)):
            try:
                await self.stop_plugin(plugin)
            except Exception:
                logger.exception("Stopping plugin %s failed during shutdown", plugin.id)
