"""Composition seams for the monitoring overview (spec 105 + RADD-1036).

The router answers infrastructure questions itself (Postgres catalog metadata is
not another module's data); anything that belongs to a MODULE is asked through
that module's public seam and reached DEFERRED + feature-detected, because every
one of them is optional and disableable.
"""

import logging
from types import ModuleType

from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings

from .schemas import MailFailureEntry, MailHealth

logger = logging.getLogger(__name__)

MAILINTAKE_MODULE = "radd.modules.mailintake"


def _mailintake() -> ModuleType | None:
    """mailintake's public seam, or None when the module is not loaded.

    The `ai` embedding-coverage precedent one step further in (spec 105's
    manifest: "monitoring never depends on an optional plugin"). Coverage is
    composed CLIENT-side because the ai module serves its own endpoint; mail
    health has no endpoint of its own, so the composition happens here and the
    dependency is declared `weak_depends` — deferred, feature-detected, and
    absent means the card simply does not exist.
    """
    if MAILINTAKE_MODULE not in settings.modules:
        return None
    from radd.modules.mailintake import service as mail_service

    return mail_service


async def mail_health(session: AsyncSession) -> MailHealth:
    """Outbound mail failures over the recent window (RADD-1036).

    Terminally-failed mail was invisible: notify's ladder gives up after four
    attempts, stamps the row, and leaves exactly two `mail.failed` events —
    which nothing aggregated, so "the customer never got it" was knowable only
    by querying the events table by hand.

    Neither the event type nor the payload shape is stated here. `mail_health`
    is mailintake's own seam, defined next to the code that EMITS those events,
    so this function is a translation into the page's wire types and nothing
    else.
    """
    mail_service = _mailintake()
    if mail_service is None:
        return MailHealth(available=False)
    health = await mail_service.mail_health(session)
    return MailHealth(
        available=True,
        window_hours=health.window_hours,
        failures=health.failures,
        given_up=health.given_up,
        capped=health.capped,
        recent=[
            MailFailureEntry(
                at=failure.at,
                recipient=failure.recipient,
                subject=failure.subject,
                error=failure.error,
                given_up=failure.given_up,
            )
            for failure in health.recent
        ],
    )
