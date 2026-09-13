import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

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
    """Directional dependency between two items in the same project (spec 14).

    `relates` is semantically symmetric — the service rejects the mirror row.
    """

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

    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), primary_key=True
    )
    label_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("labels.id", ondelete="CASCADE"), primary_key=True
    )
