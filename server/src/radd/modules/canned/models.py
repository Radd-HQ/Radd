import uuid

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class CannedResponse(Base, TimestampMixin):
    """A globally-managed comment snippet (service-desk canned reply)."""

    __tablename__ = "canned_responses"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(default=0)
