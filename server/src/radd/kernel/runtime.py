"""A process's plugin routes, hooks and scheduled loops, swapped at safe points.

Enable and disable change ONE plugin at a time, after that plugin's own admitted
work has drained (`kernel.admission`, RADD-1372). Every other plugin keeps
serving and ticking while it happens.

- **enable** closes the plugin, registers and mounts it, starts it, then opens
  it: its routes and ticks admit nothing until its startup has finished. A
  failure rolls back only what happened: the shutdown hooks run when the start
  began, and a hook that then fails is logged and noted on the original error,
  never reported in its place.
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

    A spec without an interval has no tick to schedule. A spec without its own gate
    runs under the spec-48 worker split like every hand-rolled loop."""
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
        try:
            for router in plugin.routers:
                self.app.include_router(router, prefix=settings.api_prefix, dependencies=owned)
            for spec in plugin.entities:
                entities.register_entity(spec)
                self.app.include_router(entities.crud_router(spec), prefix=settings.api_prefix,
                                        dependencies=owned)
        except BaseException:
            # A router included before the failure is not this plugin's yet
            # (`self.routes` is written below), so `unmount` could not find it.
            del self.app.routes[start:]
            raise
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

    def _started(self, plugin) -> bool:
        return any(p.id == plugin.id for p in self.started)

    def _forget(self, plugin) -> None:
        self.started[:] = [p for p in self.started if p.id != plugin.id]
        self.stopping.discard(plugin.id)

    async def start_plugin(self, plugin):
        """Run the startup hooks, then schedule the loops. The plugin counts as
        STARTED from the first hook: a start that fails halfway has hooks to
        undo, so `stop_plugin` must run for it. Loops are scheduled only when
        none of an earlier start survive (a stop that failed on a hook has
        already dropped its handles; one that failed on a loop has not), so a
        resume never runs two copies of one loop."""
        # The owner is copied into every task started here, so a loop's ticks
        # and a hook's spawned jobs are counted against this plugin.
        token = owner.set(plugin.id)
        handles = self.loops.setdefault(plugin.id, [])
        if not self._started(plugin):
            self.started.append(plugin)
        try:
            for hook in plugin.on_startup:
                await hook()
            if handles:
                logger.warning("Plugin %s keeps %d loop(s) an earlier stop could not end",
                               plugin.id, len(handles))
            else:
                for loop in schedule_tasks(plugin):
                    handles.append(loop)
                    await loop.start()
        finally:
            owner.reset(token)

    async def stop_plugin(self, plugin):
        """Stop a started plugin: each loop is forgotten as it stops, then the
        shutdown hooks run. A plugin whose start never began has nothing to
        undo, so its hooks do not run either. A hook that raises leaves the
        plugin `stopping` for the retry, with its loops already gone."""
        if not self._started(plugin) and not self.loops.get(plugin.id):
            return
        self.stopping.add(plugin.id)
        token = owner.set(plugin.id)
        try:
            handles = self.loops.get(plugin.id, [])
            while handles:
                await handles[-1].stop()
                handles.pop()
            self.loops.pop(plugin.id, None)
            for hook in plugin.on_shutdown:
                await hook()
        finally:
            owner.reset(token)
        self._forget(plugin)

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
            except BaseException as exc:
                try:
                    # A no-op unless its start began: a mount failure has no hooks to undo.
                    await self.stop_plugin(plugin)
                except Exception as stop_exc:
                    # The original failure is the one to report; the hook's rides along.
                    logger.exception("Stopping plugin %s after its failed enable also failed", plugin.id)
                    exc.add_note(f"stopping it afterwards also failed: {stop_exc!r}")
                finally:
                    self._forget(plugin)  # rolled back below: nothing of it is left to stop
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
