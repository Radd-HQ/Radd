"""Which calendar dates the SLA clock must skip (RADD-1031).

`timers.py` is pure math and takes the dates as a parameter; this is the thin
seam that goes and gets them. Providers register on the kernel's
`NON_WORKING_DAYS` socket, so `slas` never imports `leave` — with the leave
plugin absent (or disabled at runtime, which withdraws its registration) there
are no providers, the answer is empty, and every timer behaves byte-identically
to the pre-RADD-1031 build.

Personal leave is deliberately NOT here. An SLA timer belongs to an item, not to
a person, so one engineer's holiday cannot be the reason a customer's ticket
stops ageing; only a date that stops work for everybody can pause the clock.
That distinction is the socket's contract, not this module's filter.

**Retro-change rule.** Holidays are read at EVALUATION time, never stamped onto
a timer. Adding or removing a holiday therefore moves the deadline of every
still-open timer at the next evaluation — which is the point, since a studio
holiday declared on Friday must protect the tickets already running through it.
It never re-opens history: a breach is stamped once in `sla_item_states` and
`sync_states` only fires on a breach it has not already recorded, so a holiday
entered after the fact cannot un-breach a closed timer or re-fire its event. The
past is what the engine recorded at the time; the future is recomputed.
"""

import logging
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from radd.kernel import sockets

logger = logging.getLogger(__name__)


async def non_working_dates(
    session: AsyncSession, start: date, end: date
) -> frozenset[date]:
    """Every date in [start, end] on which the instance does not work.

    The UNION over all registered providers: a date is non-working if any
    calendar says so. A provider that raises is logged and skipped rather than
    failing the evaluation — a broken holiday calendar must not stop SLA
    breaches from being detected, and skipping it degrades toward the stricter
    deadline (the clock keeps running), which is the safe direction for a
    service-desk promise.
    """
    providers = sockets.providers(sockets.Socket.NON_WORKING_DAYS)
    if not providers:
        return frozenset()
    dates: set[date] = set()
    for name, provider in providers.items():
        try:
            dates.update(await provider.non_working_dates(session, start, end))
        except Exception:  # noqa: BLE001 — one bad calendar must not stop the clock
            logger.exception("sla: non-working-days provider %r failed — ignored", name)
    return frozenset(dates)
