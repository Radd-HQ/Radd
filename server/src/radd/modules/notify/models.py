import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base


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
        # The unread badge: count by recipient where read_at IS NULL.
        Index("ix_notifications_user_read", "user_id", "read_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(index=True)
    event_id: Mapped[int | None] = mapped_column(BigInteger)  # source outbox row
    type: Mapped[str] = mapped_column(String(30))  # NotificationType
    item_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    actor_id: Mapped[uuid.UUID | None]
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    read_at: Mapped[datetime | None]
    emailed_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class NotificationPref(Base):
    """Per-user notification preferences. No row = all defaults: every type on,
    email digest on. `muted_types` holds NotificationType wire strings."""

    __tablename__ = "notification_prefs"

    user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    muted_types: Mapped[list[str]] = mapped_column(JSONB, default=list)
    email_digest: Mapped[bool] = mapped_column(default=True)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
