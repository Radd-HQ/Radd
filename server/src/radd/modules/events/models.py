import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Identity, Index, String, false, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base


class ConsumerOffset(Base):
    """Where each named consumer (dispatcher, indexer, connector…) is in the stream."""

    __tablename__ = "consumer_offsets"

    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    last_event_id: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class Event(Base):
    """Append-only. `id` is the monotonic offset consumers track."""

    __tablename__ = "events"
    __table_args__ = (
        # Per-entity history feed (item History tab) + audit entity filter.
        Index("ix_events_entity", "entity_type", "entity_id"),
        # "everything user X did" — the actor-scoped audit view.
        Index("ix_events_actor_id", "actor_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # User who caused the mutation; None for system/anonymous actions. Plain UUID (no FK) —
    # events stays module-agnostic and must not depend on auth being enabled.
    actor_id: Mapped[uuid.UUID | None]
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Emitted inside an `events.quiet()` scope (a bulk import). The row is a full
    # citizen of the audit log and the search index; only the consumers that reach
    # outside the instance — notify, webhooks, automations, realtime — skip it.
    silent: Mapped[bool] = mapped_column(server_default=false(), default=False)
    # Emitted by an automation's own action (spec 116 "act as"). THE LOOP GUARD.
    #
    # It used to be enough that engine mutations carried SYSTEM_ACTOR_ID: the
    # engine skipped events whose actor was the system, so an action that
    # re-matched its own trigger applied once. "Act as" ends that — an action can
    # now run as a real person, whose events are indistinguishable from their
    # own — so causation is recorded on the EVENT instead of inferred from who
    # acted. Identity and causation are different questions and this is what
    # keeps them apart.
    automated: Mapped[bool] = mapped_column(server_default=false(), default=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
