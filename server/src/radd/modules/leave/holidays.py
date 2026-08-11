"""What `leave` contributes to the kernel's NON_WORKING_DAYS socket (RADD-1031).

An adapter, nothing more: the socket asks for dates, the service knows them.
Kept out of `service.py` so the module's public surface stays a set of functions
and the object shape exists only where the socket requires one — and out of
`__init__.py` so the manifest stays a manifest.

The consumer today is the SLA clock, which must not accrue time on a day the
studio is shut. `leave` does not know that: it answers "these dates are
non-working" and any plugin that cares reads the socket.
"""

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from . import service


class HolidayCalendar:
    """`NonWorkingDaysProvider` over this instance's declared holidays."""

    async def non_working_dates(
        self, session: AsyncSession, start: date, end: date
    ) -> set[date]:
        return await service.holiday_dates(session, start, end)
