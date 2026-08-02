import uuid
from datetime import date

from sqlalchemy import CheckConstraint, Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class LeavePeriod(Base, TimestampMixin):
    """One absence: a USER's personal leave (user_id set) or a TEAM holiday
    (team_id set) — exactly one subject. Dates are inclusive calendar days;
    holidays expand to the team's members at READ time, never materialized,
    so membership changes are always honored."""

    __tablename__ = "leave_periods"
    __table_args__ = (
        CheckConstraint("(user_id IS NULL) <> (team_id IS NULL)", name="ck_leave_one_subject"),
        CheckConstraint("start_date <= end_date", name="ck_leave_dates_ordered"),
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
    created_by: Mapped[uuid.UUID | None]
