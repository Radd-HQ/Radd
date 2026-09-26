"""The kernel PERSON_AVAILABILITY socket provider (RADD-1387): which PEOPLE are
away, for whoever hands out work (today round-robin assignment). An adapter over
`service.calendar`, so "away" means exactly what the app-wide away indicator
shows; through the socket, a runtime disable withdraws the answer."""

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
