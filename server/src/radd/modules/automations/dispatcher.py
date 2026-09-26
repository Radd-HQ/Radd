"""In-process engine loop (PeriodicLoop, gated on `run_workers`)."""

from radd.config import settings
from radd.worker import PeriodicLoop

from . import engine

_loop = PeriodicLoop(
    engine.run_once,
    interval=lambda: settings.automation_poll_interval,
    name="automation-engine",
    enabled=lambda: settings.run_workers,  # web-only process skips (spec 48 worker split)
)

start = _loop.start
stop = _loop.stop
