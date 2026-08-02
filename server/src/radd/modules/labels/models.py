import uuid

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class Label(Base, TimestampMixin):
    __tablename__ = "labels"
    __table_args__ = (UniqueConstraint("name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    color: Mapped[str | None] = mapped_column(String(7))  # "#rrggbb"
