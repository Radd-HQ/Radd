"""In-process loops, mirroring notify/dispatcher.py: the IMAP intake poller
(spec 47) and the outbound reply consumer (spec 62). Both run whenever this
process runs workers — the spec-48 split and nothing else.

**Neither loop is gated on the environment (RADD-970).** The poller used to
start only when `RADD_MAIL_IMAP_HOST` was set, which survived RADD-958 moving
mail into `mail_sources` rows and became the bug that made the move pointless:
an admin adds a mailbox in Settings → Email on an instance with no mail env
vars, the row is complete, the capability pill lights, and nothing ever polls
it. The gate is now `poller.run_once`'s own first query — `polled_sources`
empty means return 0 — so a row saved in the UI is picked up on the next tick
with no restart, and a mailbox disabled there stops being polled the same way.

That check has to live in `run_once` rather than here because `enabled` is
SYNC: `PeriodicLoop` calls it per tick and cannot await a session. The outbound
consumer already had exactly this posture (always started, `outbound_configured`
consulted per tick), so this is the two halves agreeing rather than a new idea.
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
