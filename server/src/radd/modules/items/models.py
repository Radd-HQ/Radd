import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Integer,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm.base import NEVER_SET, NO_VALUE

from radd.db import Base, TimestampMixin


class WorkItem(Base, TimestampMixin):
    __tablename__ = "work_items"
    __table_args__ = (
        UniqueConstraint("project_id", "number"),
        # The default list order is rank, and most lists are PROJECT-scoped: a
        # selective filter (members mode, `assignee = me`, quick filters) over
        # the GLOBAL rank index walks every row on a big instance to fill its
        # LIMIT (measured: 1.05s / 505k buffers for 183 matches at 503k items).
        # The composite index keeps rank-ordered scans inside the project.
        Index("ix_work_items_project_rank", "project_id", "rank"),
        # RADD-1532, measured on the 501k seed: "recently updated/created" in a
        # 100k-item project was a parallel scan and sort (about 70 ms), and "my
        # items by last update" a sort of 20k rows (64 ms); each is now an index
        # scan under 0.1 ms. Two more live only in the migration (`d1532itemindexes`)
        # because Alembic cannot express them: a trigram GIN on `title` for SLQ
        # `title ~`, and a jsonb_path_ops GIN on `custom_fields` for `@>` filters.
        Index("ix_work_items_project_updated", "project_id", text("updated_at DESC")),
        Index("ix_work_items_project_created", "project_id", text("created_at DESC")),
        Index("ix_work_items_assignee_updated", "assignee_id", text("updated_at DESC")),
        # RADD-1552: counting a project's items scanned the whole TABLE (the row
        # is wide: it carries the description), 95 ms for one project of 100k in
        # 501k. Everything a count or a per-state total reads is in this index,
        # so both are index-only: 10 ms and 14 ms.
        Index(
            "ix_work_items_project_state_cover",
            "project_id",
            "state_id",
            postgresql_include=["id", "visibility", "reporter_id", "assignee_id", "estimate_points"],
            postgresql_where=text("archived_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))  # ItemKind (hierarchy axis)
    # Issue type (spec 51) — the classification axis (Bug/Task/…), orthogonal to kind.
    # SET NULL on type deletion so an item survives losing its type (shown as untyped).
    type_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("issue_types.id", ondelete="SET NULL"), index=True
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("work_items.id"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    email_signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    state_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("states.id"), index=True)
    priority: Mapped[str] = mapped_column(String(20))
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    # Who raised the issue (service-desk requester, spec 30) — distinct from the
    # creator only when set explicitly (e.g. an agent filing on an artist's behalf).
    reporter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    team_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("teams.id"), index=True)
    # First-class shared flag (spec 24) — a core boolean attribute, not a label.
    flagged: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Spec 121: ItemVisibility — public | internal | restricted. Enforced by
    # the `@public` relation and the `item` row guard (service/visibility.py),
    # so every list, count, search and gate reads it through the same seam.
    visibility: Mapped[str] = mapped_column(
        String(20), default="public", server_default="public", index=True
    )
    # Spec 38: soft archive — hidden from lists/boards/views by default.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Manual sort key (spec 24): a fractional order for drag-to-rank; lower = earlier.
    # Assigned on create (append to bottom); reorder computes a midpoint, rebalancing
    # on float collapse. Sorted via SLQ `ORDER BY rank`.
    rank: Mapped[float] = mapped_column(Float, nullable=False, server_default="0", index=True)
    # Story points (spec 70) — a core sort/filter attribute like `rank`/`flagged`
    # (SLQ `points`, cycle/report sums). Nullable = unestimated; per-project UI
    # opt-in via SettingKey.ESTIMATION_POINTS. asdecimal=False → plain floats.
    estimate_points: Mapped[float | None] = mapped_column(
        Numeric(6, 1, asdecimal=False), nullable=True
    )
    # Planning attributes (spec 14) — all nullable/additive so live data survives.
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    cycle_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cycles.id", ondelete="SET NULL"), index=True, nullable=True
    )
    release_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("releases.id", ondelete="SET NULL"), index=True, nullable=True
    )
    custom_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    #: Counts the description's edits (RADD-1539), bumped by the attribute
    #: listener below on EVERY writer. A client that sends the version its edit
    #: started from is refused when the text has moved on since — the one field
    #: where a silent last-write-wins loses someone's paragraphs.
    description_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


@event.listens_for(WorkItem.description, "set")
def _count_description_edit(target: WorkItem, value: str, oldvalue: object, _initiator) -> None:
    if oldvalue is NO_VALUE or oldvalue is NEVER_SET or value == oldvalue:
        return  # being constructed, or restated unchanged
    target.description_version = (target.description_version or 0) + 1


class ItemKeyAlias(Base, TimestampMixin):
    """Old key → item mapping written on cross-project bulk moves (spec 68) so
    pre-move URLs/links (`/issues/TD-42`) keep resolving after the item is
    re-keyed. Consulted by the key resolvers only when the primary lookup
    misses; rows CASCADE away with the item."""

    __tablename__ = "item_key_aliases"

    old_key: Mapped[str] = mapped_column(String(60), primary_key=True)  # stored uppercase
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), index=True
    )


class ItemLink(Base):
    """Directional dependency between two items (cross-project allowed).
    `link_type` is a linktypes KEY; symmetric types reject the mirror row."""

    __tablename__ = "item_links"
    __table_args__ = (UniqueConstraint("source_item_id", "target_item_id", "link_type"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), index=True
    )
    target_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), index=True
    )
    link_type: Mapped[str] = mapped_column(String(20))  # ItemLinkType


class ItemStar(Base):
    """Per-user star/favorite on an item (spec 24) — personal, unlike the shared
    `flagged` boolean. Owned by items (mirrors item_labels/item_links)."""

    __tablename__ = "item_stars"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), primary_key=True
    )


class ItemLabel(Base):
    """Item ↔ label attachment; owned by items (labels module knows nothing about items)."""

    __tablename__ = "item_labels"
    # The primary key leads on item_id, so "every item with THIS label" scanned the
    # whole table (RADD-1532: 20.9 ms → 0.72 ms on 450k rows).
    __table_args__ = (Index("ix_item_labels_label_id", "label_id"),)

    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), primary_key=True
    )
    label_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("labels.id", ondelete="CASCADE"), primary_key=True
    )


class ItemTransition(Base):
    """One row each time an item's STATE or CYCLE changed, and one for its
    creation — the history every report folds (RADD-1537).

    Reports used to rebuild this per request from the event ledger: every
    `item.created`/`item.updated` a project ever had, loaded as ORM objects with
    their full item snapshot (about 1.5 KB each) and folded in Python on the
    event loop. This is the same fold, done once at write time by
    `items.transitions.record`, in the transaction that made the change.

    A row carries both sides of the change, so a report is one aggregate with
    no self-join: `from_*` is what the item left, `from_at` when it had entered
    that state — the stay's duration is `at - from_at`.

    Rows die with their item (CASCADE), which is what the reports want: an item
    that no longer exists is in no report. `cycle_id` is a plain uuid, as the
    ledger's own columns are — a deleted cycle's history is still history.
    """

    __tablename__ = "item_transitions"
    __table_args__ = (
        # The report window: "what happened in this project between two dates".
        Index("ix_item_transitions_project_at", "project_id", "at"),
        # One item's history in order (SLA timers, the previous-row lookup on write).
        Index("ix_item_transitions_item", "item_id", "id"),
        # Velocity and burnup: everything that happened in, or left, one cycle.
        Index(
            "ix_item_transitions_cycle", "cycle_id",
            postgresql_where=text("cycle_id IS NOT NULL"),
        ),
        Index(
            "ix_item_transitions_from_cycle", "from_cycle_id",
            postgresql_where=text("from_cycle_id IS NOT NULL"),
        ),
    )

    #: Insertion order IS the order of an item's history, as the event id was:
    #: an import restating old timestamps writes `at` out of order on purpose.
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work_items.id", ondelete="CASCADE"))
    #: The item's CURRENT project, restated on every row when it moves, so a
    #: report's window is one index range and a moved item reports where it is.
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    at: Mapped[datetime] = mapped_column(DateTime)
    state_id: Mapped[uuid.UUID]
    category: Mapped[str] = mapped_column(String(20))  # StateCategory, as of `at`
    cycle_id: Mapped[uuid.UUID | None]
    #: False = only the cycle changed; the state columns restate the current stay.
    state_changed: Mapped[bool] = mapped_column(Boolean)
    #: The item ENTERED a done-category state from outside one (throughput, velocity).
    entered_done: Mapped[bool] = mapped_column(Boolean)
    #: When the item entered `state_id` — `at` itself on a state change.
    stay_at: Mapped[datetime] = mapped_column(DateTime)
    from_state_id: Mapped[uuid.UUID | None]
    from_category: Mapped[str | None] = mapped_column(String(20))
    from_at: Mapped[datetime | None] = mapped_column(DateTime)
    from_cycle_id: Mapped[uuid.UUID | None]
