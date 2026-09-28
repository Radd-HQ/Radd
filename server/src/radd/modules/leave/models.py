import uuid
from datetime import date, time

from sqlalchemy import CheckConstraint, Date, ForeignKey, String, Time
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin

#: A same-day span needs its times ordered when both are given (RADD-1481).
#: NULL at either end means the whole day at that end, which is always ordered.
DATES_ORDERED = (
    "start_date < end_date OR (start_date = end_date AND "
    "(start_time IS NULL OR end_time IS NULL OR start_time < end_time))"
)
#: A holiday is a calendar day: the NON_WORKING_DAYS socket hands out dates.
HOLIDAY_ALL_DAY = "team_id IS NULL OR (start_time IS NULL AND end_time IS NULL)"


class LeavePeriod(Base, TimestampMixin):
    """One absence: a USER's personal leave (user_id set) or a TEAM holiday
    (team_id set) — exactly one subject. Dates are inclusive calendar days in
    the subject's own calendar; `start_time`/`end_time` (RADD-1481) narrow the
    boundary days to a wall-clock time in `timezone`, NULL meaning the whole
    day at that end. Holidays expand to the team's members at READ time, never
    materialized, so membership changes are always honored."""

    __tablename__ = "leave_periods"
    __table_args__ = (
        CheckConstraint("(user_id IS NULL) <> (team_id IS NULL)", name="ck_leave_one_subject"),
        CheckConstraint(DATES_ORDERED, name="ck_leave_dates_ordered"),
        CheckConstraint(HOLIDAY_ALL_DAY, name="ck_leave_holiday_all_day"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20))  # LeaveKind
    label: Mapped[str] = mapped_column(String(200), default="")
    start_date: Mapped[date] = mapped_column(Date, index=True)
    end_date: Mapped[date] = mapped_column(Date, index=True)
    # Wall-clock times of day in `timezone`; NULL = the whole day at that end.
    start_time: Mapped[time | None] = mapped_column(Time)
    end_time: Mapped[time | None] = mapped_column(Time)
    # The IANA zone the dates and times are read in ("" = UTC, pre-RADD-1481 rows).
    timezone: Mapped[str] = mapped_column(String(64), default="", server_default="")
    created_by: Mapped[uuid.UUID | None]
