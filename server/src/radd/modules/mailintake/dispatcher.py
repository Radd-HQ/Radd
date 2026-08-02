"""In-process loops, mirroring notify/dispatcher.py: the IMAP intake poller
(dormant unless RADD_MAIL_IMAP_HOST is configured, spec 47) and the outbound
reply consumer (always on — public-form contacts need acks/replies even with
no IMAP intake; it is a no-op sender until SMTP is configured, spec 62)."""

from radd.config import settings
from radd.worker import PeriodicLoop

from . import outbound, poller

_poll_loop = PeriodicLoop(
    poller.run_once,
    interval=lambda: settings.mail_poll_seconds,
    name="mailintake-poller",
    enabled=lambda: settings.run_workers and bool(settings.mail_imap_host),
)
_outbound_loop = PeriodicLoop(
    outbound.run_once,
    interval=lambda: settings.mail_outbound_poll_seconds,
    name="mailintake-outbound",
    enabled=lambda: settings.run_workers,  # web-only process skips (spec 48 worker split)
)


async def start() -> None:
    await _poll_loop.start()
    await _outbound_loop.start()


async def stop() -> None:
    await _poll_loop.stop()
    await _outbound_loop.stop()
