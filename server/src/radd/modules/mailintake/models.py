import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin

from .types import DEFAULT_IMAP_FOLDER, DEFAULT_IMAP_PORT, DEFAULT_SMTP_PORT


class MailContact(Base, TimestampMixin):
    """An external person on an item's mail thread (spec 62; n-ary since RADD-980).

    Unique per `(item_id, email)`. `is_primary` marks the one the singular seams
    mean by "the requester" (CSAT, the send_email `contact` role,
    `GET /items/{id}/mail-contact`): the first contact who WROTE, never demoted.
    """

    __tablename__ = "mail_contacts"
    __table_args__ = (
        # One row per address per item. The unique constraint is what makes
        # `upsert_contact` idempotent across a thread — a CC on every message
        # must refresh one row, not accumulate one per message.
        UniqueConstraint("item_id", "email", name="uq_mail_contacts_item_id_email"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(320))
    name: Mapped[str] = mapped_column(String(200), default="")
    # Most recent INBOUND RFC Message-ID this contact sent — per contact since
    # RADD-980, so a CC's reply cannot overwrite the requester's own.
    last_message_id: Mapped[str | None] = mapped_column(String(998), nullable=True)
    #: The one this item's singular seams mean. First contact captured wins, and
    #: nothing demotes it: a ticket's requester does not change because someone
    #: was copied in on message four.
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class MailMessage(Base):
    """Every RFC Message-ID Radd has sent or accepted, against its item (RADD-952).

    Idempotency: the UNIQUE constraint is the dedup mechanism — concurrent
    deliveries race on insert and the loser reports a duplicate. Threading: a
    reply's In-Reply-To/References name ids Radd SENT, so every outbound id is
    stored. `subject` keeps a thread's Subject byte-stable (a title edit must not
    re-thread every client).
    """

    __tablename__ = "mail_messages"
    __table_args__ = (
        # Lookups by message_id ride its unique index; this one serves the
        # References chain ("the thread for this item").
        Index("ix_mail_messages_item_created", "item_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    #: The RFC id INCLUDING its angle brackets, exactly as on the wire.
    message_id: Mapped[str] = mapped_column(String(998), unique=True)
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), index=True
    )
    #: The comment behind a message; NULL for the item-creating message.
    comment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("comments.id", ondelete="SET NULL"), nullable=True
    )
    direction: Mapped[str] = mapped_column(String(16))
    #: Which source an INBOUND message arrived at (RADD-979) — the earliest is the
    #: item's mail ORIGIN, which outbound answers from. `SET NULL`: losing it costs
    #: a fallback to the default sender; cascading would delete the thread.
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mail_sources.id", ondelete="SET NULL"), nullable=True, index=True
    )
    subject: Mapped[str] = mapped_column(String(998), default="")
    #: The retained RAW inbound bytes (RADD-1033) as a `BlobRef` (storage name,
    #: host — NULL = default — and size), read behind the item's gate. INBOUND only;
    #: NULL when retention is off or no storage host is configured.
    raw_storage_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_host_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("storage_hosts.id", ondelete="SET NULL"), nullable=True
    )
    raw_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), index=True
    )


class MailSource(Base, TimestampMixin):
    """Where mail comes IN (RADD-958): a row per ingest point; env seeds the first
    row once (the spec-101 rule)."""

    __tablename__ = "mail_sources"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(32))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    #: The address this source accepts mail for; also in the self-loop guard's set.
    address: Mapped[str] = mapped_column(String(320), default="")
    #: webhook: the HMAC secret; imap: the mailbox password. Write-only over the API,
    #: secretbox ciphertext at rest (RADD-1446; decrypted by the ingest router and
    #: the poller's login alone).
    secret: Mapped[str] = mapped_column(Text, default="")
    #: BLANK on a preset kind (gmail/outlook), which answers it at read time —
    #: `resolve.source_host`. Storing the preset's value would freeze it.
    host: Mapped[str] = mapped_column(String(255), default="")  # imap only
    port: Mapped[int] = mapped_column(Integer, default=DEFAULT_IMAP_PORT)
    username: Mapped[str] = mapped_column(String(320), default="")
    folder: Mapped[str] = mapped_column(String(120), default=DEFAULT_IMAP_FOLDER)
    #: Where a message lands when NO rule matches. The chain narrows from here.
    default_project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )
    #: "Send replies from" (RADD-979); NULL = the default sender. `SET NULL`: a lost
    #: binding degrades to the default rather than taking the mailbox with it.
    sender_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mail_senders.id", ondelete="SET NULL"), nullable=True
    )
    #: The `Authentication-Results` authserv-id whose SPF/DKIM/DMARC verdict this
    #: source trusts (RADD-1032), e.g. `mx.radd-hq.com`. Blank = trust nothing (the
    #: default): `From:` taken at face value. Set, a fail-or-absent verdict is
    #: attributed to SYSTEM. Opt-in: the header is only as trustworthy as the MX.
    trusted_authserv_id: Mapped[str | None] = mapped_column(String(255), nullable=True)


class MailSender(Base, TimestampMixin):
    """Where mail goes OUT (RADD-958). `from_address` is also the self-loop
    guard's comparison: mail from it arriving at a source IS the loop."""

    __tablename__ = "mail_senders"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(32))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    from_address: Mapped[str] = mapped_column(String(320), default="")
    #: Overrides the source's address; normally blank.
    reply_to: Mapped[str] = mapped_column(String(320), default="")
    #: BLANK on a preset kind — see `MailSource.host`.
    host: Mapped[str] = mapped_column(String(255), default="")
    port: Mapped[int] = mapped_column(Integer, default=DEFAULT_SMTP_PORT)
    username: Mapped[str] = mapped_column(String(320), default="")
    #: The SMTP password: secretbox ciphertext at rest (RADD-1446; `SmtpSender` decrypts).
    secret: Mapped[str] = mapped_column(Text, default="")
    starttls: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class MailRule(Base, TimestampMixin):
    """One step of a source's ordered routing chain (RADD-958/961); first enabled
    match by `position` wins. Deliberately small: anything expressible as an
    automation on `mail.received` belongs there."""

    __tablename__ = "mail_rules"
    __table_args__ = (Index("ix_mail_rules_source_position", "source_id", "position"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mail_sources.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(200))
    rule_type: Mapped[str] = mapped_column(String(32))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    position: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    #: Per-type config, validated by the handler's own pydantic model.
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    #: The outcome. A matching rule with NULL project still STOPS the chain (on the
    #: source default), which is why the UI shows what matched.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )


class MailSignatureSettings(Base):
    __tablename__ = "mail_signature_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    rules: Mapped[list] = mapped_column(JSONB, default=list)
