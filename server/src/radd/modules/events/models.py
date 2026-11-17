import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Identity, Index, Integer, SmallInteger, String, Text, UniqueConstraint, false, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base


#: `pg_current_xact_id()` is an xid8; through text it is a plain bigint, which is
#: what a cursor column and a row-value comparison want.
XACT_ID_DEFAULT = "(pg_current_xact_id()::text)::bigint"


class ConsumerOffset(Base):
    """Where each named consumer (dispatcher, indexer, connector…) is in the stream."""

    __tablename__ = "consumer_offsets"

    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    last_event_id: Mapped[int] = mapped_column(BigInteger, default=0)
    #: The transaction half of the cursor (RADD-1524): consumers walk the stream
    #: in `(xact_id, id)` order, so the position is that pair, never the id alone.
    last_xact_id: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class ConsumerFailure(Base):
    """An event a consumer's handler raised on (RADD-1538) — what used to be a
    log line and a lost side effect. `pending` rows are retried by the consumer
    itself at `next_attempt_at`; `dead` ones wait for an operator to replay or
    discard them (Settings → Monitoring). See `consumer.py`."""

    __tablename__ = "consumer_failures"
    __table_args__ = (
        UniqueConstraint("consumer", "event_id"),
        # The retry read: this consumer's pending rows that have come due.
        Index("ix_consumer_failures_due", "consumer", "status", "next_attempt_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    consumer: Mapped[str] = mapped_column(String(100))
    #: Plain id, no FK: the ledger may be pruned under a failure row, and a
    #: failure whose event is gone is simply dropped at the next attempt.
    event_id: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # FailureStatus
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    first_failed_at: Mapped[datetime] = mapped_column(DateTime)
    last_failed_at: Mapped[datetime] = mapped_column(DateTime)


class Event(Base):
    """Append-only. Consumers track `(xact_id, id)` — NOT `id` alone: an id is
    taken at flush, so a transaction that commits late holds an id below ones
    already consumed, and a cursor on `id` passed over its event for good
    (RADD-1524). See `service.read_after`."""

    __tablename__ = "events"
    __table_args__ = (
        # Per-entity history feed (item History tab) + audit entity filter.
        Index("ix_events_entity", "entity_type", "entity_id"),
        # "everything user X did" — the actor-scoped audit view.
        Index("ix_events_actor_id", "actor_id"),
        # Spec 123: "everything that happened in project X".
        Index("ix_events_project_id", "project_id"),
        # The consumer walk: `(xact_id, id) > cursor` in that order (RADD-1524).
        Index("ix_events_xact_id_id", "xact_id", "id"),
        # Two more live in the migration (`d123ledger`) because Alembic cannot
        # express them: a trigram GIN over `search_text` (guarded on pg_trgm)
        # and a GIN over `payload -> 'changes'` for the changed-field filter.
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    #: The id of the transaction that wrote the row, stamped by the database.
    #: Rows from before the column existed carry 0, below every real transaction.
    xact_id: Mapped[int] = mapped_column(BigInteger, server_default=text(XACT_ID_DEFAULT))
    # User who caused the mutation; None for system/anonymous actions. Plain UUID (no FK) —
    # events stays module-agnostic and must not depend on auth being enabled.
    actor_id: Mapped[uuid.UUID | None]
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Spec 123 — the LEDGER columns, derived by `emit` from what the payload
    # already carries (subject refs), so an emitter declares nothing new:
    #: the project the event happened in (plain uuid, no FK — see actor_id).
    project_id: Mapped[uuid.UUID | None]
    #: the entity's display label at write time (`RADD-123 Board scroll`) —
    #: what the audit page shows and links, and what survives the row's deletion.
    entity_label: Mapped[str | None] = mapped_column(String(300))
    #: what free-text search matches: the event's label, the entity's label,
    #: the changed fields and their old/new values. Indexed by trigram.
    search_text: Mapped[str | None] = mapped_column(Text)
    # Emitted inside an `events.quiet()` scope (a bulk import). The row is a full
    # citizen of the audit log and the search index; only the consumers that reach
    # outside the instance — notify, webhooks, automations, realtime — skip it.
    silent: Mapped[bool] = mapped_column(server_default=false(), default=False)
    # Emitted by an automation's action (spec 116) — THE LOOP GUARD; see `quiet.automated`.
    automated: Mapped[bool] = mapped_column(server_default=false(), default=False)
    #: RADD-1315 — which automation's run wrote it, at what chain depth (see
    #: `quiet.AutomationCause`). NULL / 0 when not automated.
    automation_rule_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    automation_depth: Mapped[int] = mapped_column(SmallInteger, server_default="0", default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
