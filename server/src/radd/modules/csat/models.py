import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class CsatSurvey(Base, TimestampMixin):
    """One satisfaction survey per item, ever (spec 65). The row's existence is
    the once-only guard — reopen→re-resolve never resends — and the unguessable
    token is the requester's credential on the public rating page. `rating` stays
    NULL until the requester responds; re-submits overwrite it (latest wins) but
    `responded_at` is stamped only once."""

    __tablename__ = "csat_surveys"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), unique=True
    )
    token: Mapped[str] = mapped_column(String(64), unique=True)  # secrets.token_urlsafe(32)
    rating: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)  # 1–5
    comment: Mapped[str] = mapped_column(Text, default="")
    sent_at: Mapped[datetime]
    responded_at: Mapped[datetime | None] = mapped_column(nullable=True)
