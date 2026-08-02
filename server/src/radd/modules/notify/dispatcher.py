"""In-process loops (consumer + email digests), mirroring webhooks/dispatcher.py.
Moves to the dedicated worker entrypoint when that lands (single-instance today)."""

from radd.config import settings
from radd.worker import PeriodicLoop

from . import consumer, emailer

_consumer_loop = PeriodicLoop(
    consumer.run_once,
    interval=lambda: settings.notify_poll_interval,
    name="notify-consumer",
    enabled=lambda: settings.run_workers,  # web-only process skips (spec 48 worker split)
)
_email_loop = PeriodicLoop(
    emailer.run_once,
    interval=lambda: settings.notify_email_interval,
    name="notify-emailer",
    enabled=lambda: settings.run_workers,
    sleep_first=True,  # no digest burst on startup; batching gets a full window
)


async def start() -> None:
    await _consumer_loop.start()
    await _email_loop.start()


async def stop() -> None:
    await _consumer_loop.stop()
    await _email_loop.stop()
