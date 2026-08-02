import uuid

from sqlalchemy import ForeignKey, String
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
