import uuid
from datetime import date

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
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
    """A work item's original estimate (absence = none). Here, not on work_items, so
    items never depends on time logging; remaining is derived, never stored."""

    __tablename__ = "item_estimates"

    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), primary_key=True
    )
    original_estimate_seconds: Mapped[int] = mapped_column(Integer)


class Worklog(Base, TimestampMixin):
    """A logged-work entry, booked to a calendar day (a Date: no timezone math).
    Against an item, or ITEMLESS (spec 59) with an optional project; an itemless
    entry must carry a category, which is what identifies it (CHECK + service)."""

    __tablename__ = "worklogs"
    __table_args__ = (
        CheckConstraint(
            "item_id IS NOT NULL OR category_id IS NOT NULL",
            name="ck_worklogs_scope",
        ),
        # RADD-1258: one row per SOURCE entry — this index, not the lookup, makes
        # backfills, redeliveries and races land on ONE row. Hand-logged rows have
        # no external id and stay out of it.
        Index(
            "uq_worklogs_external",
            "external_source",
            "external_id",
            unique=True,
            postgresql_where=text("external_id <> ''"),
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
    # RADD-1258 — a MIRRORED entry's provenance: `external_source` a VcsProvider
    # value ('' = logged here), `external_scope` the ref (`pr:<repo>:<n>`) so a
    # reconcile never touches another MR's rows, `external_id` the provider's id.
    # A row with a source is read-only here.
    external_source: Mapped[str] = mapped_column(String(20), default="", server_default="")
    external_scope: Mapped[str] = mapped_column(String(512), default="", server_default="")
    external_id: Mapped[str] = mapped_column(String(512), default="", server_default="")
