"""The kernel NON_WORKING_DAYS socket provider (RADD-1031): holiday dates, for
whichever plugin reads the socket (today the SLA clock)."""

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from . import service


class HolidayCalendar:
    """`NonWorkingDaysProvider` over this instance's declared holidays."""

    async def non_working_dates(
        self, session: AsyncSession, start: date, end: date
    ) -> set[date]:
        return await service.holiday_dates(session, start, end)
