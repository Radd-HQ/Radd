import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class Cycle(Base, TimestampMixin):
    """A global iteration (cycle). Status is DERIVED from the dates, not
    stored — except an explicit close: `completed_at` (the Jira "Complete sprint"
    action) marks a cycle completed even mid-window."""

    __tablename__ = "cycles"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    # Nullable: a cycle with no dates is a DRAFT (staging) cycle — see types.cycle_status.
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    goal: Mapped[str] = mapped_column(Text, default="")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    #: RADD-1291: the project the cycle belongs to — who plans it and whose
    #: Planning/Reports list it first. NOT a scope: a cycle still holds issues
    #: from any project (cross-project sprints are why cycles were global).
    #: NULL = an instance cycle. SET NULL when the project goes.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), index=True, nullable=True
    )


class CycleTeam(Base):
    """Team association on a cycle (spec 60): NO rows = a public cycle (everyone
    today's behavior); any rows = visible only to members of
    the listed teams (+ cycle managers/admins). Full-replace on write."""

    __tablename__ = "cycle_teams"

    cycle_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cycles.id", ondelete="CASCADE"), primary_key=True
    )
    team_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True
    )


class CycleSeries(Base, TimestampMixin):
    """A recurring cycle LABEL ("PIPE" → PIPE - 115, PIPE - 116 …). Cycles belong to
    a series by NAME (label + trailing number, `types.cycle_label`) — no FK, so
    pre-existing and imported cycles join their series automatically. The series
    carries the auto-provisioning config: how many future drafts to keep, and the
    next number to mint (overridable — a Jira import may already sit at 120)."""

    __tablename__ = "cycle_series"
    __table_args__ = (UniqueConstraint("label"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    label: Mapped[str] = mapped_column(String(180))
    drafts_ahead: Mapped[int] = mapped_column(Integer, default=1)
    next_number: Mapped[int] = mapped_column(Integer, default=1)
    # Optional cadence (both set = scheduled): provisioned cycles get real timelines —
    # start on this weekday (Python convention, 0=Monday), run duration_days, chained
    # back-to-back after the label's latest scheduled cycle. Unset = dateless drafts.
    start_weekday: Mapped[int | None] = mapped_column(Integer)
    duration_days: Mapped[int | None] = mapped_column(Integer)


class ItemCycleRecord(Base):
    """One stint of an item in a cycle (spec 56): opened when the item enters,
    closed (`removed_at`) when it leaves. `work_items.cycle_id` stays the
    CURRENT-cycle truth; this table is the first-class, SLQ-queryable history
    (`past_cycle`) — carryovers survive cycle-completion moves, unlike the
    event log which is an audit surface, not a query surface."""

    __tablename__ = "item_cycle_records"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), index=True
    )
    cycle_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cycles.id", ondelete="CASCADE"), index=True
    )
    added_at: Mapped[datetime] = mapped_column(DateTime)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime)
