"""In-process sender loop; a cursor-advancing no-op while mail or CSAT_ENABLED is off."""

from radd.config import settings
from radd.worker import PeriodicLoop

from . import sender

_loop = PeriodicLoop(
    sender.run_once,
    interval=lambda: settings.csat_poll_seconds,
    name="csat-sender",
    enabled=lambda: settings.run_workers,  # web-only process skips (spec 48 worker split)
)

start = _loop.start
stop = _loop.stop
