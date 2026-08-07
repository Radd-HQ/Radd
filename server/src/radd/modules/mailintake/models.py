import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
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
