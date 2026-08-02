import uuid

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from radd.db import Base, TimestampMixin


class LinkTypeDef(Base, TimestampMixin):
    """A user-definable issue link type (spec 91). Scope lives in the
    `item_link_type_projects` association — NO rows = global (every project), rows =
    only those projects (mirrors field scope). `work_items` links reference a type
    by KEY (a plain string on `item_links`), not this id, so the key is immutable."""

    __tablename__ = "item_link_types"
    __table_args__ = (UniqueConstraint("key"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(60))
    outward_name: Mapped[str] = mapped_column(String(60))  # "blocks"
    inward_name: Mapped[str] = mapped_column(String(60))  # "is blocked by"
    direction: Mapped[str] = mapped_column(String(20))  # LinkDirection
    # A built-in (blocks/relates/duplicates/mentions): key + direction are locked and
    # it can't be deleted. `auto_managed` (mentions) is derived from text, not the API.
    system: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_managed: Mapped[bool] = mapped_column(Boolean, default=False)
    project_links: Mapped[list["LinkTypeProject"]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def project_ids(self) -> list[uuid.UUID]:
        """The projects this type is scoped to; empty = global."""
        return [link.project_id for link in self.project_links]


class LinkTypeProject(Base):
    """One project a link type is scoped to (spec 91). No rows = global."""

    __tablename__ = "item_link_type_projects"

    link_type_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("item_link_types.id", ondelete="CASCADE"), primary_key=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
