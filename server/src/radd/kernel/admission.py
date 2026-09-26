"""Per-owner admission: which plugin's code is running right now (RADD-1341, RADD-1372).

Every unit of plugin work is admitted under its OWNER, the plugin whose route,
periodic loop or spawned job it is, and counted against that owner until it
finishes:

- an HTTP request to a plugin's router, from admission until its response has
  been SENT, a stream included (`RuntimeMiddleware` releases it, not the
  dependency);
- a periodic tick (`RuntimeGate.work`), owned by the plugin whose startup
  started the loop: `PluginRuntime.start_plugin` sets the `owner` ContextVar,
  and the loop's task copies it;
- a job started with `spawn`, owned by whatever work spawned it.

Changing plugin X closes X's admissions and waits for X's count to reach zero.
Nothing else is paused or drained, so a long import or an SSE stream in one
plugin never holds up a toggle of another. Admission is refused only per owner:
while X is closed, and, for a NON-CORE plugin, while this process's lease has
lapsed (its acknowledgement is going stale, so the cluster may already have
disabled X without this process knowing). Core plugins, unowned routes
(/health, the SPA) and the backup status endpoints are never refused here.

Cross-plugin calls are not counted against the callee: a request to A that
calls into B is A's work. Disabling B requires that no loaded plugin depends on
it, and a registry read sees B either wholly present or wholly gone.
"""

import asyncio
import math
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from enum import StrEnum
from typing import Any

owner: ContextVar[str | None] = ContextVar("plugin_owner", default=None)

#: ASGI scope keys set by `RuntimeMiddleware`: the owners admitted on this
#: connection, and (WebSocket) the send callable used to close it.
ADMITTED_KEY = "radd.admitted"
SEND_KEY = "radd.send"
#: WebSocket close codes (RFC 6455 registry): the owner is changing state, or
#: its state is unconfirmed and the client should reconnect later.
CLOSE_SERVICE_RESTART = 1012
CLOSE_TRY_AGAIN_LATER = 1013


class LeaseState(StrEnum):
    """Whether this process can currently vouch for its plugin state."""

    UNLEASED = "unleased"  # no reconciler bound (tools, tests): nothing to confirm against
    HELD = "held"
    LAPSED = "lapsed"


class DrainTimeout(TimeoutError):
    """An owner's admitted work did not finish in time. Nothing was cancelled."""

    def __init__(self, plugin_id: str, in_flight: int) -> None:
        super().__init__(f"{in_flight} request(s) or job(s) of {plugin_id} still running")
        self.plugin_id = plugin_id
        self.in_flight = in_flight


def _settings():
    from radd.config import settings

    return settings


class RuntimeGate:
    def __init__(self) -> None:
        self.counts: dict[str | None, int] = {}
        self.closed: set[str] = set()
        #: Held while the app starts its plugins: periodic ticks wait, because a
        #: run function may touch a table a later plugin's startup ensures.
        self.ticks_held = False
        self.lease_until: float | None = None
        self.drain_timeout = _settings().plugin_drain_timeout_seconds
        self.sockets: dict[asyncio.Task, tuple[str, Any]] = {}
        self._waiters: set[asyncio.Future] = set()

    # --- change notification: waiters re-check their own condition ---------
    def _notify(self) -> None:
        for waiter in list(self._waiters):
            if waiter.get_loop().is_closed():
                self._waiters.discard(waiter)  # a torn-down event loop: nobody is waiting
            elif not waiter.done():
                waiter.set_result(None)

    async def _changed(self) -> None:
        waiter = asyncio.get_running_loop().create_future()
        self._waiters.add(waiter)
        try:
            await waiter
        finally:
            self._waiters.discard(waiter)

    # --- lease ---------------------------------------------------------------
    def lease_state(self) -> LeaseState:
        if self.lease_until is None:
            return LeaseState.UNLEASED
        return LeaseState.HELD if time.monotonic() < self.lease_until else LeaseState.LAPSED

    def renew(self, until: float | None) -> None:
        self.lease_until = until
        self._notify()

    def uncertain(self, plugin_id: str | None) -> bool:
        """A non-core plugin's desired state cannot be confirmed: the lease lapsed."""
        if plugin_id is None or self.lease_state() is not LeaseState.LAPSED:
            return False
        from .registry import registries

        plugin = registries.plugins.get(plugin_id)
        return plugin is not None and not plugin.core

    # --- accounting ----------------------------------------------------------
    def add(self, plugin_id: str | None) -> None:
        self.counts[plugin_id] = self.counts.get(plugin_id, 0) + 1

    def done(self, plugin_id: str | None) -> None:
        remaining = self.counts.get(plugin_id, 0) - 1
        if remaining > 0:
            self.counts[plugin_id] = remaining
            return
        self.counts.pop(plugin_id, None)
        self._notify()

    def refusal(self, plugin_id: str) -> str | None:
        """Why a new request to `plugin_id` is refused right now, or None."""
        from .registry import registries

        if plugin_id in self.closed or plugin_id not in registries.plugins:
            return "Plugin is changing state"
        if self.uncertain(plugin_id):
            return "Plugin state is unconfirmed while this process reconnects"
        return None

    @asynccontextmanager
    async def work(self):
        """Admit one periodic tick under the current owner. Never fails: it
        waits while plugins are starting, while its owner is closed, and while
        its owner is uncertain."""
        plugin_id = owner.get()
        while self.ticks_held or (
            plugin_id is not None and (plugin_id in self.closed or self.uncertain(plugin_id))
        ):
            await self._changed()
        self.add(plugin_id)
        try:
            yield
        finally:
            self.done(plugin_id)

    # --- changes -------------------------------------------------------------
    def hold_ticks(self) -> None:
        self.ticks_held = True

    def release_ticks(self) -> None:
        self.ticks_held = False
        self._notify()

    def close(self, plugin_id: str) -> None:
        """Refuse new work for `plugin_id` (requests 503, ticks wait) until `open`."""
        self.closed.add(plugin_id)

    def open(self, plugin_id: str) -> None:
        if plugin_id in self.closed:
            self.closed.discard(plugin_id)
            self._notify()

    async def drain(self, plugin_id: str) -> None:
        """Wait until none of `plugin_id`'s admitted work remains.

        Its admissions must already be closed, so the count only falls and the
        loop re-checks after every wake-up: there is no window in which new
        work can join. Admitted work is never cancelled to force a change
        through; DrainTimeout after `drain_timeout` and the caller retries."""
        try:
            async with asyncio.timeout(self.drain_timeout):
                while self.counts.get(plugin_id):
                    await self._changed()
        except TimeoutError as exc:
            raise DrainTimeout(plugin_id, self.counts.get(plugin_id, 0)) from exc

    async def close_sockets(self, plugin_id: str) -> None:
        tasks = []
        for task, (pid, send) in list(self.sockets.items()):
            if pid == plugin_id:
                if send is not None:
                    try:
                        await send({"type": "websocket.close", "code": CLOSE_SERVICE_RESTART})
                    except Exception:  # Transport may already be closed; still cancel and drain the session.
                        pass
                task.cancel()
                tasks.append(task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


gate = RuntimeGate()


def spawn(coro: Awaitable[Any], *, name: str | None = None) -> asyncio.Task:
    """Adopt a request-spawned job under the current owner, so disabling that
    plugin waits for its writes and nothing else does."""
    plugin_id = owner.get()
    current = gate
    current.add(plugin_id)  # before scheduling: also covers tasks that have not started yet

    async def run():
        return await coro

    task = asyncio.create_task(run(), name=name)

    def finished(task: asyncio.Task) -> None:
        current.done(plugin_id)
        if task.cancelled():
            coro.close()

    task.add_done_callback(finished)
    return task


class RuntimeMiddleware:
    """Releases each admitted HTTP request only after its response has been sent,
    and ends a WebSocket whose owner became uncertain. Refuses nothing itself:
    admission is per owner, in the router dependency below."""

    def __init__(self, app: Callable) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        kind = scope["type"]
        if kind not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        admitted: list[str] = []
        scope[ADMITTED_KEY] = admitted
        if kind == "http":
            current = gate
            try:
                await self.app(scope, receive, send)
            finally:
                for plugin_id in admitted:
                    current.done(plugin_id)
            return
        scope[SEND_KEY] = send

        async def leased_receive():
            message = await receive()
            if message["type"] != "websocket.disconnect" and any(map(gate.uncertain, admitted)):
                await send({"type": "websocket.close", "code": CLOSE_TRY_AGAIN_LATER})
                return {"type": "websocket.disconnect", "code": CLOSE_TRY_AGAIN_LATER}
            return message

        await self.app(scope, leased_receive, send)


def admission(plugin_id: str):
    """The dependency every owned router carries, generated CRUD included."""
    from fastapi import HTTPException, WebSocketException
    from starlette.requests import HTTPConnection

    async def admit(connection: HTTPConnection):
        scope = connection.scope
        websocket = scope["type"] == "websocket"
        refusal = gate.refusal(plugin_id)
        if refusal is not None:
            if websocket:
                uncertain = gate.uncertain(plugin_id)
                raise WebSocketException(
                    code=CLOSE_TRY_AGAIN_LATER if uncertain else CLOSE_SERVICE_RESTART
                )
            retry = str(math.ceil(_settings().plugin_reconcile_interval_seconds))
            raise HTTPException(503, refusal, headers={"Retry-After": retry})
        admitted = scope.get(ADMITTED_KEY)
        # A socket is long-lived: it is CLOSED when its owner is disabled, never drained.
        held = not websocket
        current = gate
        if held:
            current.add(plugin_id)
        if admitted is not None:
            admitted.append(plugin_id)
        token = owner.set(plugin_id)
        task = asyncio.current_task()
        if websocket:
            current.sockets[task] = (plugin_id, scope.get(SEND_KEY))
        try:
            yield
        finally:
            current.sockets.pop(task, None)
            owner.reset(token)
            if held and admitted is None:
                current.done(plugin_id)  # not behind RuntimeMiddleware (tools, tests): release here

    return admit
