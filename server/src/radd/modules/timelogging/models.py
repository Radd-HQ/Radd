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
        # RADD-1258: one row per SOURCE entry. A mirrored worklog carries the
        # provider's own entry id, and this index — not the lookup — is what
        # makes a backfill after a webhook, a re-delivered webhook, or two
        # deliveries racing land on ONE row (the `uq_item_vcs_links_ref`
        # precedent). Hand-logged rows carry no external id and stay out of it.
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
    # RADD-1258 — provenance of a MIRRORED entry (time logged on a merge request
    # or pull request at the provider and copied here). `external_source` is a
    # VcsProvider value ('' = logged in Radd); `external_scope` names the ref the
    # time was logged on (`pr:<repo>:<n>`, the vcs link's external id) so a
    # reconcile can drop the entries that vanished at the source WITHOUT
    # touching another MR's rows on the same item; `external_id` is the
    # provider's own entry id. A row with a source is read-only in Radd — it
    # is corrected where it was logged.
    external_source: Mapped[str] = mapped_column(String(20), default="", server_default="")
    external_scope: Mapped[str] = mapped_column(String(200), default="", server_default="")
    external_id: Mapped[str] = mapped_column(String(200), default="", server_default="")
