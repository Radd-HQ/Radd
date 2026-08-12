import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Index, String, func, text
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
        # The unread badge: count by recipient where read_at IS NULL — and, since
        # spec 118, where the row is an INBOX row at all. `inbox` joins the index
        # rather than being filtered after it, because every badge poll in every
        # open tab runs this count.
        Index("ix_notifications_user_read", "user_id", "read_at", "inbox"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(index=True)
    event_id: Mapped[int | None] = mapped_column(BigInteger)  # source outbox row
    type: Mapped[str] = mapped_column(String(30))  # NotificationType
    item_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    actor_id: Mapped[uuid.UUID | None]
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Spec 118: the CHANNEL verdict, stamped at the write. Before this, "in the
    # inbox" was the row existing and "by email" was re-derived per tick from the
    # recipient's preferences — which meant the mailer could only ask a
    # relation-free question (`is this TYPE emailed`), because the row had
    # forgotten how its recipient was connected to the subject by the time it got
    # there. Two booleans, and both loops read the decision instead of retaking
    # it. `off` writes no row at all, so neither is ever false together.
    inbox: Mapped[bool] = mapped_column(default=True, server_default="true")
    email: Mapped[bool] = mapped_column(default=False, server_default="false")
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
    """Per-user notification settings that are not per-kind (spec 118).

    One column left. `muted_types` and `email_types` — RADD-686's two per-type
    lists — moved into `notification_rules`, where the same answer can be given
    per RELATIONSHIP and per subscription instead of once for the whole
    instance; the migration (`d118notifrules`) carried every stored row across.
    Whether to send a DIGEST is the one preference with no scope to it: it is
    about the shape of the mail, not about which events reach you.

    No row = digest on.
    """

    __tablename__ = "notification_prefs"

    user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    email_digest: Mapped[bool] = mapped_column(default=True)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class NotificationRule(Base):
    """One cell-set of one person's notification matrix (spec 118).

    A row is (user, scope, scope_id) → a SPARSE map of kind → channel. Sparse is
    the point: a rule states what it has an opinion about and stays silent about
    the rest, so subscribing to a project's new issues cannot quietly overwrite
    what you said about comments on your own work. `rules.resolve` walks the
    scopes most-specific-first and takes the first opinion it finds.

    **Two partial unique indexes, not one constraint.** The relationship scopes
    (`own`/`participating`/`teams`) carry `scope_id = NULL`, and Postgres counts
    NULLs as distinct in a unique index — so a single UNIQUE (user_id, scope,
    scope_id) would happily store a person's `own` rule twice, and the resolver
    would then answer with whichever row the planner happened to index last.
    Splitting on `scope_id IS NULL` gives both halves a real uniqueness
    guarantee without a sentinel uuid standing in for "no target".
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
        # Fan-out's question, asked once per event: who subscribed to THIS
        # project / space / team? Without it, widening the recipient set means a
        # sequential scan of every rule row on every item event.
        Index("ix_notification_rules_target", "scope", "scope_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Plain UUID (no FK), like every other id in this module — notify stays
    # auth-schema-agnostic.
    user_id: Mapped[uuid.UUID] = mapped_column(index=True)
    scope: Mapped[str] = mapped_column(String(20))  # RuleScope
    #: The project/space/team this subscribes to; NULL for a relationship scope.
    scope_id: Mapped[uuid.UUID | None]
    #: {NotificationType wire string: Channel wire string} — sparse.
    channels: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
