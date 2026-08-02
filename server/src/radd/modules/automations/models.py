import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class AutomationRule(Base, TimestampMixin):
    """An event-driven rule (specs 15+58): when the `trigger` event type fires and
    `event_conditions` match the event, items matching `condition_slq` get
    `actions` applied by the engine as the system actor."""

    __tablename__ = "automation_rules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # An event-type string from catalog.TRIGGERS ("item.updated", …) or "manual".
    trigger: Mapped[str] = mapped_column(String(100))
    # Structured condition tree over the triggering event (spec 58); NULL = always.
    event_conditions: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # '' = always match; otherwise SLQ compiled+validated on write.
    condition_slq: Mapped[str] = mapped_column(Text, default="")
    # List of {type, params} — the validated action union, stored as raw JSON.
    actions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    position: Mapped[int] = mapped_column(Integer, default=0)
    # Spec 69: {kind, minutes|time, weekdays} (schemas.ScheduleConfig) — present
    # iff trigger == AutomationTrigger.SCHEDULE, NULL otherwise.
    schedule: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class AutomationScheduleState(Base):
    """Scheduler bookkeeping per scheduled rule (spec 69) — mirrors the
    sla_item_states pattern: engine state kept apart from user data. The row is
    (re)computed on rule create/update/enable and advanced by the scheduler in
    the same transaction that emits `automation.scheduled` (at-most-once per
    occurrence; a missed window fires once on the next tick, never a backlog)."""

    __tablename__ = "automation_schedule_state"

    rule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("automation_rules.id", ondelete="CASCADE"), primary_key=True
    )
    next_run_at: Mapped[datetime]  # naive UTC, like every engine timestamp
    last_run_at: Mapped[datetime | None]
