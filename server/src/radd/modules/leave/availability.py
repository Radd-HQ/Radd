"""What `leave` contributes to the kernel's PERSON_AVAILABILITY socket (RADD-1387).

The per-person sibling of `holidays.py`: that one tells an SLA clock which dates
nobody works; this one tells whoever hands out work which PEOPLE are away. An
adapter over `service.calendar`, which already expands a team holiday to the
team's current members — so "away" here means exactly what the app-wide away
indicator shows.

The consumer today is round-robin assignment in `automations`, which used to
import this module's service behind a `settings.modules` check. That check read
BOOT config, so a leave plugin disabled at runtime kept deciding who got
tickets; through the socket, disabling it withdraws the answer with it.
"""

import uuid
from collections.abc import Collection
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from . import service


class LeaveAvailability:
    """`PersonAvailabilityProvider` over recorded leave and team holidays."""

    async def away_user_ids(
        self, session: AsyncSession, day: date, user_ids: Collection[uuid.UUID]
    ) -> set[uuid.UUID]:
        wanted = set(user_ids)
        if not wanted:
            return set()
        return {
            entry.user_id
            for entry in await service.calendar(session, day, day)
            if entry.user_id in wanted
        }
