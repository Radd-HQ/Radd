import uuid

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from radd.db import Base, TimestampMixin


class Screen(Base, TimestampMixin):
    """A field-layout for one scope. `issue_type_id` NULL = the project's default
    screen (used by items whose type has no screen of its own)."""

    __tablename__ = "screens"
    __table_args__ = (UniqueConstraint("project_id", "issue_type_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    issue_type_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("issue_types.id", ondelete="CASCADE"), nullable=True
    )
    fields: Mapped[list["ScreenField"]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ScreenField.position",
    )


class ScreenField(Base):
    """One field's placement within a screen. `field` is a builtin token
    (`ScreenBuiltinField`) or a `cf:<key>` custom-field id."""

    __tablename__ = "screen_fields"
    __table_args__ = (UniqueConstraint("screen_id", "field"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    screen_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("screens.id", ondelete="CASCADE"), index=True
    )
    field: Mapped[str] = mapped_column(String(60))
    placement: Mapped[str] = mapped_column(String(10))  # ScreenPlacement
    position: Mapped[int] = mapped_column(Integer, default=0)
