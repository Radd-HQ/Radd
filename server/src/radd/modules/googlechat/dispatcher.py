"""In-process consumer loop, mirroring notify/dispatcher.py. Dormant unless
RADD_GOOGLECHAT_WEBHOOK_URL is configured (spec 47) AND this process runs
workers (spec 48 split — was URL-only, so a web-only process could double-
consume the cursor alongside the worker)."""

from radd.config import settings
from radd.worker import PeriodicLoop

from . import consumer

_loop = PeriodicLoop(
    consumer.run_once,
    interval=lambda: settings.googlechat_poll_interval,
    # web-only process skips (spec 48 worker split); unconfigured URL — stay dormant
    enabled=lambda: settings.run_workers and bool(settings.googlechat_webhook_url),
    name="googlechat-notifier",
)

start = _loop.start
stop = _loop.stop
