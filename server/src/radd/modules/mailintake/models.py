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
    """An external person on an item's mail thread (spec 62, n-ary since RADD-980).

    **`item_id` used to be the PRIMARY KEY**, which said "one external contact
    per ticket, ever". Real desk mail does not have that shape: a customer CCs a
    colleague, a colleague replies instead, an account manager is copied on the
    first message. Every one of them was invisible to Radd — the second sender
    only refreshed `last_message_id`, so their address was never recorded and the
    answer went to one person out of the three who asked.

    So a contact is now a ROW, unique per `(item_id, email)`, and `is_primary`
    marks the one the item's other machinery still means when it says "the
    requester": the CSAT survey, the `contact` recipient role of the send_email
    action, and the singular `GET /items/{id}/mail-contact`. Exactly one row per
    item carries it — the FIRST contact captured, which on a mail-born ticket is
    the person who wrote in.

    `last_message_id` is per contact for the same reason the table is n-ary:
    it is "the last thing THIS person said", and one column shared by three
    people is a fact about none of them.
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
    #: Which source the message ARRIVED at (RADD-979) — the item's mail ORIGIN.
    #: Written on INBOUND rows only; NULL on everything outbound, and on every
    #: item that was never born from mail. It is the fact outbound reads back to
    #: answer from the address the conversation actually lives on: a ticket
    #: raised at `help@` was previously replied to by whichever single sender
    #: was marked default, so the requester never saw the address they wrote to.
    #: `SET NULL` because losing the origin costs a fallback to the default
    #: sender, and cascading would delete the thread with the mailbox.
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mail_sources.id", ondelete="SET NULL"), nullable=True, index=True
    )
    subject: Mapped[str] = mapped_column(String(998), default="")
    #: The RAW inbound bytes, retained per `MAIL_RAW_RETENTION_DAYS` through the
    #: spec-102 blob seam (RADD-1033). NULL when retention is off, when the
    #: message carried no Message-ID to key a row off, or when no storage host is
    #: configured. Three columns because that is a `BlobRef`: the opaque storage
    #: name, the host it lives on (NULL = the default host), and the size. Reads
    #: sit behind the item's own gate, mounted at the download endpoint like any
    #: attachment. Only INBOUND rows ever carry these — an outbound message is one
    #: Radd composed and already has in full.
    raw_storage_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_host_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("storage_hosts.id", ondelete="SET NULL"), nullable=True
    )
    raw_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
    #: "Send replies from" — the sender that ANSWERS for this address (RADD-979).
    #: NULL = the default sender, which is what every source did before.
    #: `SET NULL` on the relay's deletion: a binding is a preference, and losing
    #: it must degrade to the default rather than take the mailbox with it.
    sender_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("mail_senders.id", ondelete="SET NULL"), nullable=True
    )
    #: The `Authentication-Results` authserv-id whose SPF/DKIM/DMARC verdict this
    #: source trusts (RADD-1032) — the MX's own stamp, e.g. `mx.radd-hq.com`.
    #: NULL/blank = trust nothing, which is the DEFAULT and reproduces today's
    #: behaviour exactly: `From:` is taken at face value for attribution. Set it,
    #: and a message whose verdict from THIS authserv is fail-or-absent is
    #: recorded as received but attributed to SYSTEM, never to the account whose
    #: address it forged. This is Radd trusting its gateway's verdict, not doing
    #: crypto — the header is only as trustworthy as the MX that stamps it, which
    #: is why it is opt-in per source.
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
    #: Overrides the source's address when set. Normally blank, so replies go
    #: back to the mailbox that received the original.
    reply_to: Mapped[str] = mapped_column(String(320), default="")
    #: BLANK on a preset kind — see `MailSource.host`.
    host: Mapped[str] = mapped_column(String(255), default="")
    port: Mapped[int] = mapped_column(Integer, default=DEFAULT_SMTP_PORT)
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
