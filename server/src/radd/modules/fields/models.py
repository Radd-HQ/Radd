import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from radd.db import Base, TimestampMixin


class FieldDefinition(Base, TimestampMixin):
    __tablename__ = "field_definitions"
    __table_args__ = (UniqueConstraint("key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # No scope rows = global; rows scope the field to those projects. selectin: `project_ids` is always loaded.
    project_links: Mapped[list["FieldProject"]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    key: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(20))
    required: Mapped[bool] = mapped_column(Boolean, default=False)
    options: Mapped[list[str] | None] = mapped_column(JSONB)
    # Value seeded onto new items when the payload omits this key (spec 50 follow-up).
    # JSONB so it holds any field-type shape (scalar, or a list for multi_select).
    # NULL = no default. Validated against type/options on write.
    default_value: Mapped[Any | None] = mapped_column(JSONB)
    # spec 52: how the field renders (FieldDisplay) — mainly select/multi_select
    # (chips vs a compact dropdown, to avoid chip overflow). NULL = the type default.
    display: Mapped[str | None] = mapped_column(String(20))
    indexed: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_visible: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(String(20))

    @property
    def project_ids(self) -> list[uuid.UUID]:
        """The projects this field is scoped to; empty = global (see project_links)."""
        return [link.project_id for link in self.project_links]


class FieldProject(Base):
    """One project a field is scoped to (see FieldDefinition.project_links)."""

    __tablename__ = "field_definition_projects"

    field_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("field_definitions.id", ondelete="CASCADE"), primary_key=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
