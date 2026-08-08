import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base

from .types import default_email_type_values


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
    # RADD-997: per-row send backoff, shared by the mailer and the digest and
    # applied in `retry.py`. A failed send used to leave the row exactly as the
    # selection found it, so the 5-second mailer re-tried it every tick for the
    # whole 24-hour age window — an SMTP connection and a `mail.failed` event
    # each time. `email_attempts` counts failures; `email_next_try` is the
    # earliest tick allowed to reconsider the row (NULL = now, which is every
    # row that has never failed). Exhausting the ladder stamps `emailed_at`.
    email_attempts: Mapped[int] = mapped_column(default=0, server_default="0")
    email_next_try: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class NotificationPref(Base):
    """Per-user notification preferences — a per-type CHANNEL matrix (RADD-686).

    No row = all defaults: every type reaches the inbox, `DEFAULT_EMAIL_TYPES`
    are also mailed as they happen, digest on. Both list columns hold
    NotificationType wire strings.

    **Email requires inbox.** `muted_types` silences BOTH channels, because a
    muted type never becomes a notification row and rows are what get mailed
    (`mailer`). `email_types` is therefore always stored disjoint from
    `muted_types` — `service.set_prefs` normalises rather than rejecting, so a
    raw API caller cannot store a contradiction the mailer would have to
    interpret.
    """

    __tablename__ = "notification_prefs"

    user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    muted_types: Mapped[list[str]] = mapped_column(JSONB, default=list)
    # A row written without naming the column means the documented defaults —
    # the same answer an absent row gives. `[]` would mean "email nothing".
    email_types: Mapped[list[str]] = mapped_column(JSONB, default=default_email_type_values)
    email_digest: Mapped[bool] = mapped_column(default=True)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
