import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class Release(Base, TimestampMixin):
    """A project-scoped release/version. An ordinary API resource a CI service-account
    or the automations engine can POST to and assign — no special path."""

    __tablename__ = "releases"
    __table_args__ = (UniqueConstraint("project_id", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[str] = mapped_column(String(100))  # e.g. "BNX.2.3"
    status: Mapped[str] = mapped_column(String(20), default="planned")  # ReleaseStatus
    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
