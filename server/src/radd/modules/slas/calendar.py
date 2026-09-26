"""Which calendar dates the SLA clock skips (RADD-1031): the union of the
NON_WORKING_DAYS socket's providers; none registered = no dates.

Only dates that stop work for everybody — never personal leave: a timer belongs
to an item, not a person. Read at EVALUATION time: a new holiday moves every
open deadline but never reopens history (breaches are stamped once).
"""

import logging
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from radd.kernel import sockets

logger = logging.getLogger(__name__)


async def non_working_dates(
    session: AsyncSession, start: date, end: date
) -> frozenset[date]:
    """Every date in [start, end] any provider calls non-working. A provider that
    raises is logged and skipped: a broken calendar must not stop breach
    detection, and skipping errs toward the stricter deadline."""
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
