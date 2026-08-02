import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class SlaPolicy(Base, TimestampMixin):
    """Response/resolution targets for one project (spec 67: policies are
    project-level; workspace-wide policies are retired)."""

    __tablename__ = "sla_policies"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    response_minutes: Mapped[int | None] = mapped_column(Integer)
    resolution_minutes: Mapped[int | None] = mapped_column(Integer)
    # State NAMES that pause the clock (e.g. "Waiting for artist") — resolved
    # against each item's project at evaluation time.
    pause_state_names: Mapped[list] = mapped_column(JSONB, default=list)
    # Spec 35: count only the instance work week (RADD_WORK_WEEK_DAYS) —
    # non-working days pause the clock.
    work_week_only: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    # Spec 63: Priority values this policy applies to; [] = every priority.
    priorities: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    # Spec 63: first-match resolution order — policies are tried by
    # (position, created_at); the first scope+priority match wins.
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Spec 63: daily business-hours window (minutes from midnight, both-or-neither,
    # start < end). The clock also pauses outside [start, end) each active day.
    business_start_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    business_end_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Spec 69: emit sla.due_soon when a timer's remaining active time drops to
    # this many minutes (NULL = no pre-breach warning).
    warning_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)


class SlaItemState(Base):
    """Engine bookkeeping per (item, policy): stamped deadlines/mets so a breach
    event fires exactly once. Display always recomputes live."""

    __tablename__ = "sla_item_states"

    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), primary_key=True
    )
    policy_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sla_policies.id", ondelete="CASCADE"), primary_key=True
    )
    response_due_at: Mapped[datetime | None]
    response_met_at: Mapped[datetime | None]
    response_breached_at: Mapped[datetime | None]
    resolution_due_at: Mapped[datetime | None]
    resolution_met_at: Mapped[datetime | None]
    resolution_breached_at: Mapped[datetime | None]
    # Spec 69: sla.due_soon fired-once stamps (per kind), like the breach stamps.
    warned_response_at: Mapped[datetime | None]
    warned_resolution_at: Mapped[datetime | None]
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
