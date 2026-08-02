import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class IssueType(Base, TimestampMixin):
    """A per-project issue type (spec 51) — the classification axis. Name is unique
    per project; `is_default` marks the type new items get when none is chosen."""

    __tablename__ = "issue_types"
    __table_args__ = (UniqueConstraint("project_id", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    color: Mapped[str] = mapped_column(String(7))  # "#rrggbb"
    icon: Mapped[str | None] = mapped_column(String(40))  # lucide key, nullable
    position: Mapped[int] = mapped_column(Integer, default=0)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    # Issue template (spec 76): markdown prefilled into the new-item description
    # when this type is selected (swapped while the draft is still pristine).
    # NULL = no template. Served on IssueTypeRead — no extra endpoint.
    description_template: Mapped[str | None] = mapped_column(Text, nullable=True)
