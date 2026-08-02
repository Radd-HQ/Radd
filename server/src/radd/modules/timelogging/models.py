import uuid
from datetime import date

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class ProjectTimeLogging(Base, TimestampMixin):
    """Per-project enablement of time logging. Absence of a row == disabled (opt-in)."""

    __tablename__ = "project_timelogging"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class WorkCategory(Base, TimestampMixin):
    """A globally-configurable category for a worklog (Investigation, Meeting, …).

    Data (like labels/states), not a hardcoded enum — admins curate the list. Archived
    categories stay attached to historical worklogs but drop out of the picker.
    """

    __tablename__ = "work_categories"
    __table_args__ = (UniqueConstraint("name", name="uq_work_categories_name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    position: Mapped[int] = mapped_column(Integer, default=0)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class ItemEstimate(Base, TimestampMixin):
    """A work item's original estimate (one row per item; absence == no estimate).

    Kept in this module's table rather than on work_items so time logging stays a
    per-project-optional plugin the items module doesn't depend on. Remaining is
    derived (estimate − logged), never stored.
    """

    __tablename__ = "item_estimates"

    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), primary_key=True
    )
    original_estimate_seconds: Mapped[int] = mapped_column(Integer)


class Worklog(Base, TimestampMixin):
    """A single logged-work entry, booked to a calendar day (`worked_on`).

    Scope (spec 59): against an item (the classic path — item_id set, scope
    derived from the item), or ITEMLESS (meetings/admin/general time) with an
    optional project refinement. Itemless entries must carry a category — the
    category is what identifies them everywhere (enforced by the CHECK below
    plus service validation). Bucketing by a plain Date (not a datetime) keeps
    the timesheet free of timezone math.
    """

    __tablename__ = "worklogs"
    __table_args__ = (
        CheckConstraint(
            "item_id IS NOT NULL OR category_id IS NOT NULL",
            name="ck_worklogs_scope",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), index=True, nullable=True
    )
    # Itemless anchors (spec 59): project refinement is optional.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=True
    )
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("work_categories.id", ondelete="SET NULL"), index=True, nullable=True
    )
    worked_on: Mapped[date] = mapped_column(Date, index=True)
    time_spent_seconds: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(Text, default="")
