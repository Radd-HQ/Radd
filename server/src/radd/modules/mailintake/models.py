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
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class MailContact(Base, TimestampMixin):
    """The external requester behind an item (spec 62) — captured when intake or a
    public form submission resolves the sender to NO active user. One contact per
    item (v1): a later distinct sender on the same thread only refreshes
    `last_message_id`, never the address. Acks, outbound comment replies, and
    CSAT surveys (spec 65) address this row.
    """

    __tablename__ = "mail_contacts"

    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), primary_key=True
    )
    email: Mapped[str] = mapped_column(String(320))
    name: Mapped[str] = mapped_column(String(200), default="")
    # Most recent INBOUND RFC Message-ID on the thread — feeds the outbound
    # In-Reply-To/References headers so replies land in the requester's thread.
    last_message_id: Mapped[str | None] = mapped_column(String(998), nullable=True)


class MailMessage(Base):
    """Every RFC Message-ID Radd has sent or accepted, against its item (RADD-952).

    Two jobs, one table, and neither was previously done:

    **Idempotency.** An inbound id seen inside `DEDUP_WINDOW` is a retry, not a
    second ticket. The UNIQUE constraint is the mechanism — not a SELECT then an
    INSERT, because two concurrent deliveries of the same message are exactly
    what a provider retry produces and check-then-act loses that race. The insert
    races; the loser catches the integrity error and reports a duplicate.

    **Threading.** A reply's `In-Reply-To` / `References` name ids Radd SENT, and
    before this nothing recorded them: `mail_contacts.last_message_id` holds one
    INBOUND id per item and is overwritten on every reply. Threading therefore
    fell through to the subject key, which is the last-resort mechanism.

    `subject` is stored so a thread's Subject stays byte-stable for its whole
    life — deriving it from the item title instead means a title edit silently
    re-threads the conversation in every participant's client.
    """

    __tablename__ = "mail_messages"
    __table_args__ = (
        # Threading resolves (item_id) FROM a message_id; dedup asks whether a
        # message_id exists at all. Both are covered by the unique index on
        # message_id; this one serves "the thread for this item", which the
        # References chain needs.
        Index("ix_mail_messages_item_created", "item_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    #: The RFC id INCLUDING its angle brackets, exactly as it appeared on the
    #: wire. Normalising would mean guessing at what a client will send back.
    message_id: Mapped[str] = mapped_column(String(998), unique=True)
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), index=True
    )
    #: Which comment produced an outbound message. NULL for inbound and for the
    #: item-creating message, which precedes any comment.
    comment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("comments.id", ondelete="SET NULL"), nullable=True
    )
    direction: Mapped[str] = mapped_column(String(16))
    subject: Mapped[str] = mapped_column(String(998), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), index=True
    )


class MailSource(Base, TimestampMixin):
    """Where mail comes IN (RADD-958).

    A row per ingest point, so pointing Radd at a customer's own
    `support@company.com` is configuration rather than a deployment. `kind`
    selects the implementation — the seam that makes a Gmail adapter a class
    plus a row.

    Env seeds the first row on an empty database and is then never read again:
    the spec-101 rule Sign-in, Storage and AI all follow and that email was the
    last holdout from.
    """

    __tablename__ = "mail_sources"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(32))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    #: The address this source accepts mail for — `help@radd-hq.com`. Also what
    #: outbound puts in Reply-To, and half of the self-loop guard's set.
    address: Mapped[str] = mapped_column(String(320), default="")
    #: webhook: the HMAC secret. imap: the mailbox password. Write-only over the
    #: API, like every other credential in this instance.
    secret: Mapped[str] = mapped_column(Text, default="")
    host: Mapped[str] = mapped_column(String(255), default="")  # imap only
    port: Mapped[int] = mapped_column(Integer, default=993)
    username: Mapped[str] = mapped_column(String(320), default="")
    folder: Mapped[str] = mapped_column(String(120), default="INBOX")
    #: Where a message lands when NO rule matches. The chain narrows from here.
    default_project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True
    )


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
    #: Overrides the source's address when set. Normally blank, so replies go
    #: back to the mailbox that received the original.
    reply_to: Mapped[str] = mapped_column(String(320), default="")
    host: Mapped[str] = mapped_column(String(255), default="")
    port: Mapped[int] = mapped_column(Integer, default=587)
    username: Mapped[str] = mapped_column(String(320), default="")
    secret: Mapped[str] = mapped_column(Text, default="")
    starttls: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class MailRule(Base, TimestampMixin):
    """One step of a source's ordered routing chain (RADD-958/961).

    Before this, where a message landed was one line: a plus-address tag if it
    named a real project, else one instance-wide default. "Mail to `pipeline@`
    opens in DEV" was inexpressible.

    **Deliberately small.** A rule decides where a message lands, BEFORE an item
    exists; an automation reacts to the item and `mail.received` once it does
    (RADD-960). Anything expressible as an automation belongs there — let this
    grow and it becomes a second, worse automation engine with no graph editor
    and no run history.

    First enabled match by `position` wins; no match falls to the source's
    default project.
    """

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
    #: Per-type config, validated by the handler's own pydantic model — the
    #: storage-rule shape, so a plugin's rule kind needs no column here.
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    #: The outcome. NULL project on a matching rule means "this rule only
    #: decorates" — it still stops the chain, which is the surprising part and
    #: why the UI has to show what matched.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
