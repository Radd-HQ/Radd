"""In-process sender loop, mirroring mailintake's outbound dispatcher. Always
started under `run_workers` (spec 48 split): the guards live inside `run_once`
— with SMTP or every project's CSAT_ENABLED off it is a cursor-advancing no-op,
so enabling either later never replays the backlog."""

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
