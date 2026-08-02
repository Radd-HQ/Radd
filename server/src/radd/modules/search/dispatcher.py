"""In-process indexer loop, mirroring the other outbox consumers."""

from radd.config import settings
from radd.worker import PeriodicLoop

from . import indexer

_loop = PeriodicLoop(
    indexer.run_once,
    interval=lambda: settings.search_poll_interval,
    name="search-indexer",
    enabled=lambda: settings.run_workers,  # web-only process skips (spec 48 worker split)
)

start = _loop.start
stop = _loop.stop
