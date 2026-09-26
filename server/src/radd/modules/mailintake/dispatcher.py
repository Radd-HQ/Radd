"""In-process loops: the IMAP poller (spec 47) and the outbound consumer
(spec 62), started whenever this process runs workers. Neither is gated on the
environment (RADD-970): `PeriodicLoop.enabled` is sync, so each loop's own first
query decides whether there is anything to do — a mailbox added in Settings →
Email is polled on the next tick with no restart.
"""

from radd.config import settings
from radd.worker import PeriodicLoop

from . import outbound, poller

_poll_loop = PeriodicLoop(
    poller.run_once,
    interval=lambda: settings.mail_poll_seconds,
    name="mailintake-poller",
    enabled=lambda: settings.run_workers,  # the ROWS decide; see the module docstring
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
