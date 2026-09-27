import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base

from .types import NotificationDelivery


class ItemWatcher(Base):
    """A user following an item — added manually or auto-watched (assign/comment/create)."""

    __tablename__ = "item_watchers"

    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), primary_key=True
    )
    # Plain UUID (no FK) — like events.actor_id, notify stays auth-schema-agnostic.
    user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Notification(Base):
    """One in-app notification for one recipient, fanned out from an outbox event.

    `payload` carries display values resolved at write time (item key/title, actor
    name, excerpt, from/to) so the record renders without joins and stays accurate
    after renames — same philosophy as the item `changes` diffs.
    """

    __tablename__ = "notifications"
    __table_args__ = (
        # The unread badge: every open tab polls this count, so `inbox` joins the index.
        Index("ix_notifications_user_read", "user_id", "read_at", "inbox"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(index=True)
    event_id: Mapped[int | None] = mapped_column(BigInteger)  # source outbox row
    type: Mapped[str] = mapped_column(String(30))  # NotificationType
    item_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    actor_id: Mapped[uuid.UUID | None]
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Spec 118: the channel verdict, stamped at write time while the relation is
    # known; `off` writes no row, so the two are never both false.
    inbox: Mapped[bool] = mapped_column(default=True, server_default="true")
    email: Mapped[bool] = mapped_column(default=False, server_default="false")
    read_at: Mapped[datetime | None]
    #: RADD-1457: the email channel's verdict (`NotificationDelivery`); the mail
    #: loops select on it. `emailed_at` is set only when a transport accepted it.
    delivery: Mapped[str] = mapped_column(
        String(20),
        default=NotificationDelivery.PENDING.value,
        server_default=NotificationDelivery.PENDING.value,
    )
    emailed_at: Mapped[datetime | None]
    # RADD-997: send backoff (`retry.py`); NULL next_try = eligible now.
    email_attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    email_next_try: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class NotificationPref(Base):
    """Per-user settings with no per-kind scope: only `email_digest` (spec 118
    moved the per-type lists into `notification_rules`). No row = digest on."""

    __tablename__ = "notification_prefs"

    user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    email_digest: Mapped[bool] = mapped_column(default=True)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class NotificationRule(Base):
    """One person's opinions for one scope (spec 118): (user, scope, scope_id) →
    a SPARSE {kind: channel} map; `rules.resolve` takes the first opinion found.

    Two PARTIAL unique indexes, not one constraint: relationship scopes carry
    `scope_id = NULL`, and Postgres treats NULLs as distinct, so one UNIQUE
    would allow a person two `own` rows.
    """

    __tablename__ = "notification_rules"
    __table_args__ = (
        Index(
            "uq_notification_rules_subscription",
            "user_id",
            "scope",
            "scope_id",
            unique=True,
            postgresql_where=text("scope_id IS NOT NULL"),
        ),
        Index(
            "uq_notification_rules_relationship",
            "user_id",
            "scope",
            unique=True,
            postgresql_where=text("scope_id IS NULL"),
        ),
        # Fan-out's per-event question: who subscribed to THIS project/space/team?
        Index("ix_notification_rules_target", "scope", "scope_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(index=True)  # plain UUID, like ItemWatcher's
    scope: Mapped[str] = mapped_column(String(20))  # RuleScope
    #: The project/space/team this subscribes to; NULL for a relationship scope.
    scope_id: Mapped[uuid.UUID | None]
    #: {NotificationType wire string: Channel wire string} — sparse.
    channels: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
