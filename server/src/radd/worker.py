"""Shared background-loop scaffold for the in-process workers.

Every outbox consumer / periodic engine runs the same skeleton: tick, log
(never crash the loop) on failure, honour cancellation, sleep, repeat. Modules
instantiate a `PeriodicLoop` with their tick coroutine and wire its
`start`/`stop` into `on_startup`/`on_shutdown`; the gate (`enabled`) and the
interval stay per-module lambdas so config is read live at each tick.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


class LocalLoopBackend:
    """The default `task_backend` socket provider (spec 93 / A8, §6) — today's
    poll-loop runner, wrapped in the TaskBackend interface so a `celery` plugin can
    provide an alternative by registering another `task_backend` provider. Consumers
    migrating from hand-rolled `PeriodicLoop`s to `schedule()` is incremental."""

    def __init__(self) -> None:
        self._loops: list["PeriodicLoop"] = []

    def schedule(self, name, run, interval, gate=None) -> "PeriodicLoop":
        loop = PeriodicLoop(
            run,
            interval=interval if callable(interval) else (lambda: float(interval)),
            name=name,
            enabled=gate or (lambda: True),
        )
        self._loops.append(loop)
        return loop

    def enqueue(self, name, run):
        return asyncio.create_task(run(), name=name)

    async def run_workers(self) -> None:
        for loop in self._loops:
            await loop.start()


# The default TaskBackend singleton — registered on the `task_backend` socket.
LOCALLOOP = LocalLoopBackend()


class PeriodicLoop:
    """Owns one background task. `stop()` resets the task handle so a later
    `start()` restarts cleanly (test lifecycles re-enter the app lifespan).
    `sleep_first=True` delays the first tick a full interval (digest-style
    loops: no burst on startup, batching gets a whole window).
    `drain=True` re-ticks immediately while `run_once` reports work (a truthy
    return), so a backlog is chewed at full speed and the interval only paces
    the idle poll — a 500k-row embedding backfill must not pay the sleep per
    batch. Incompatible with `sleep_first` (a drain loop has no batching window)."""

    def __init__(
        self,
        run_once: Callable[[], Awaitable[object]],
        *,
        interval: Callable[[], float],
        name: str,
        enabled: Callable[[], bool],
        sleep_first: bool = False,
        drain: bool = False,
    ) -> None:
        if drain and sleep_first:
            raise ValueError("drain and sleep_first are mutually exclusive")
        self._run_once = run_once
        self._interval = interval
        self._name = name
        self._enabled = enabled
        self._sleep_first = sleep_first
        self._drain = drain
        self._task: asyncio.Task | None = None

    async def _run(self) -> None:
        while True:
            if self._sleep_first:
                await asyncio.sleep(self._interval())
            worked = False
            try:
                worked = bool(await self._run_once())
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("%s iteration failed", self._name)
            if self._drain and worked:
                await asyncio.sleep(0)  # yield to the event loop, then keep draining
                continue
            if not self._sleep_first:
                await asyncio.sleep(self._interval())

    async def start(self) -> None:
        if not self._enabled():
            return
        self._task = asyncio.create_task(self._run(), name=self._name)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
