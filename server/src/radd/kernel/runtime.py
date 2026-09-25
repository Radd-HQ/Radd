"""Safe points for runtime contribution changes.

Requests and worker ticks retain the registry until they finish. A change stops
new worker ticks and admissions to the affected plugin, then swaps contributions
at a quiet point. Other HTTP requests remain available while work drains.
"""
import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
import time

from starlette.responses import JSONResponse

owner: ContextVar[str | None] = ContextVar('plugin_owner', default=None)


class RuntimeGate:
    def __init__(self):
        self.count = 0
        self.drain_timeout = 30
        self.changing = False
        self.exclusive = False
        self.blocked: set[str] = set()
        self.wake = asyncio.Event()
        self.wake.set()
        self.idle = asyncio.Event()
        self.idle.set()
        self.lease_until: float | None = None
        self.sockets: dict[asyncio.Task, tuple[str, object]] = {}

    def available(self):
        return self.lease_until is None or time.monotonic() < self.lease_until

    def add(self):
        self.count += 1
        self.idle.clear()

    def done(self):
        self.count -= 1
        if not self.count:
            self.idle.set()

    @asynccontextmanager
    async def work(self, *, background=False):
        while self.exclusive or (background and self.changing):
            await self.wake.wait()
        if not self.available():
            raise RuntimeError('Plugin runtime lease expired; waiting for reconciliation')
        self.add()
        try:
            yield
        finally:
            self.done()

    @asynccontextmanager
    async def change(self, plugin_id):
        self.changing = True
        self.blocked.add(plugin_id)
        self.wake.clear()
        try:
            # Do not cancel admitted work to force a change through. Retry later
            # and expose the failure if a long request/job has not drained yet.
            async with asyncio.timeout(self.drain_timeout):
                await self.idle.wait()
            self.exclusive = True
            yield
        finally:
            self.exclusive = False
            self.changing = False
            self.blocked.discard(plugin_id)
            self.wake.set()

    async def close_sockets(self, plugin_id):
        tasks = []
        for task, (pid, send) in list(self.sockets.items()):
            if pid == plugin_id:
                try:
                    await send({'type': 'websocket.close', 'code': 1012})
                except Exception:  # Transport may already be closed; still cancel and drain the session.
                    pass
                task.cancel()
                tasks.append(task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


gate = RuntimeGate()


def spawn(coro, *, name=None):
    """Adopt request-spawned jobs so a disable cannot abandon their writes."""
    gate.add()  # before scheduling: also covers tasks that have not started yet

    async def run():
        return await coro

    task = asyncio.create_task(run(), name=name)
    def finished(task):
        gate.done()
        if task.cancelled():
            coro.close()
    task.add_done_callback(finished)
    return task


class RuntimeMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'websocket':
            if not gate.available():
                return await send({'type': 'websocket.close', 'code': 1013})
            scope['_plugin_send'] = send
            async def leased_receive():
                message = await receive()
                if not gate.available() and message['type'] != 'websocket.disconnect':
                    await send({'type': 'websocket.close', 'code': 1013})
                    return {'type': 'websocket.disconnect', 'code': 1013}
                return message
            return await self.app(scope, leased_receive, send)
        if scope['type'] != 'http' or scope.get('path') == '/health':
            return await self.app(scope, receive, send)
        if not gate.available():
            return await JSONResponse({'detail': 'Plugin runtime is reconnecting'}, status_code=503,
                                      headers={'Retry-After': '2'})(scope, receive, send)
        async with gate.work():
            await self.app(scope, receive, send)


def admission(plugin_id):
    """Dependency attached to each owned router, including generated CRUD."""
    from fastapi import HTTPException
    from starlette.requests import HTTPConnection

    async def admit(connection: HTTPConnection):
        from .registry import registries
        if plugin_id in gate.blocked or plugin_id not in registries.plugins:
            if connection.scope['type'] == 'websocket':
                from fastapi import WebSocketException
                raise WebSocketException(code=1012)
            raise HTTPException(503, 'Plugin is changing state', headers={'Retry-After': '2'})
        token = owner.set(plugin_id)
        task = asyncio.current_task()
        if connection.scope['type'] == 'websocket':
            gate.sockets[task] = (plugin_id, connection.scope['_plugin_send'])
        try:
            yield
        finally:
            gate.sockets.pop(task, None)
            owner.reset(token)
    return admit


class PluginRuntime:
    """Owns routes, hooks, and scheduled loops for this application process."""
    def __init__(self, app):
        self.app = app
        self.routes: dict[str, list] = {}
        self.loops: dict[str, list] = {}
        self.started: list = []
        self.base_handlers = dict(app.exception_handlers)

    def mount(self, plugin):
        from fastapi import Depends
        from radd.config import settings
        from . import entities
        start = len(self.app.routes)
        for router in plugin.routers:
            self.app.include_router(router, prefix=settings.api_prefix,
                                    dependencies=[Depends(admission(plugin.id))])
        for spec in plugin.entities:
            entities.register_entity(spec)
            self.app.include_router(entities.crud_router(spec), prefix=settings.api_prefix,
                                    dependencies=[Depends(admission(plugin.id))])
        added = self.app.routes[start:]
        del self.app.routes[start:]
        # API routes precede the plugin-assets/SPA fallback, including late enables.
        index = getattr(self, 'route_end', len(self.app.routes))
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
            node = getattr(node, 'app', None)

    async def start_plugin(self, plugin):
        from radd.config import settings
        from .sockets import Socket, provider
        token = owner.set(plugin.id)
        self.loops.setdefault(plugin.id, [])
        try:
            for hook in plugin.on_startup:
                await hook()
            backend = provider(Socket.TASK_BACKEND, settings.task_backend)
            if plugin.tasks and backend is None:
                raise RuntimeError('No task backend is available')
            for spec in plugin.tasks:
                if spec.interval is not None:
                    loop = backend.schedule(spec.name, spec.run, spec.interval,
                                            gate=spec.gate or (lambda: settings.run_workers))
                    self.loops[plugin.id].append(loop)
                    await loop.start()
            self.started.append(plugin)
        finally:
            owner.reset(token)

    async def stop_plugin(self, plugin):
        for loop in reversed(self.loops.get(plugin.id, [])):
            await loop.stop()
        for hook in plugin.on_shutdown:
            await hook()
        self.loops.pop(plugin.id, None)
        self.started[:] = [p for p in self.started if p.id != plugin.id]

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
        import importlib
        from . import entities
        from .loader import _check_subjects
        from .registry import registries
        async with gate.change(plugin.id):
            from dataclasses import fields
            snapshot = {field.name: getattr(registries, field.name).copy() for field in fields(registries)}
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

    async def disable(self, plugin):
        from .registry import registries
        async with gate.change(plugin.id):
            await gate.close_sockets(plugin.id)
            await self.stop_plugin(plugin)
            registries.unregister_plugin(plugin)
            self.unmount(plugin)

    async def shutdown(self):
        for plugin in reversed(list(self.started)):
            await self.stop_plugin(plugin)
