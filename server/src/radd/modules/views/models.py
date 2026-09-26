import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class View(Base, TimestampMixin):
    """A saved view: a named board/list/planning/roadmap over an SLQ query.

    `owner_id` is the accountable owner (NULL on seeded project views, which the
    view.* atoms manage). Per-subject shares are access grants (resource "view");
    `global_access` is the ShareLevel every active user gets (NULL = not public).
    `project_id` NULL = all projects. `group_by`/`swimlane_by` are axis tokens
    (a ViewAxis value or cf.<select-key>) and must differ.
    """

    __tablename__ = "views"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    view_type: Mapped[str] = mapped_column(String(20))  # ViewType
    query: Mapped[str] = mapped_column(Text, default="")  # SLQ
    group_by: Mapped[str | None] = mapped_column(Text)  # axis token; None = ungrouped
    swimlane_by: Mapped[str | None] = mapped_column(Text)  # axis token; None = no swimlanes
    # RADD-855: per-VIEW bucket order — lists of bucket KEYS, loosely coupled
    # like card_layout (unknown keys ignored, unlisted buckets append in
    # natural order), so a renamed state or new category degrades gracefully.
    column_order: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    swimlane_order: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Board column presence — part of the shared view, never a personal preference.
    # hidden_columns: bucket keys, loosely validated like column_order; NULL = none hidden.
    collapse_empty_columns: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    hidden_columns: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Optional cycle-name REGEX narrowing the header set when an axis is `cycle`
    # (specs 23/56); None/'' = all cycles. Compile-validated; matched client-side.
    cycle_filter: Mapped[str | None] = mapped_column(Text)
    # Jira-style quick filters: [{name, query}] chips shown on the view; an active
    # chip's SLQ is AND-ed (parenthesized) into the fetch. Conditions only — no
    # ORDER BY (validated on write).
    quick_filters: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    # SOFT WIP limits (spec 76): {state_id: int>=1} rendered on state-axis board
    # column headers (n/limit, amber at, red above). Display-only — nothing blocks
    # a drop. NULL = no limits. Project-scoped views validate keys against the
    # project's states (409); all-projects boards accept any UUID key (their
    # buckets are name-keyed, so a limit only shows where the key matches).
    wip_limits: Mapped[dict[str, int] | None] = mapped_column(JSONB, nullable=True)
    # Spec 108: ordered LIST-surface column ids (builtin names or `cf.<key>`);
    # NULL = the type's default set. Widths are deliberately NOT here — they're
    # per-user ergonomics (localStorage), the column SET is the shared shape.
    columns: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    # Spec 109: the board-card layout — {v, cells: [{attr,row,col,span,align}],
    # max_labels}. NULL = the type's default card. Shared shape like `columns`;
    # per-user ergonomics (scale) stay client-side. Attr ids are validated
    # loosely so a departed custom field degrades instead of bricking the view.
    card_layout: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    # ShareLevel every active user gets, or NULL = not globally visible
    # (spec 57; setting it is gated on view.create — it's a server-wide broadcast).
    global_access: Mapped[str | None] = mapped_column(String(10))
    position: Mapped[int] = mapped_column(Integer, default=0)


class ViewMember(Base, TimestampMixin):
    """An item hand-pinned to a view. Writes ride the view edit gate; reads go
    through the item dialect (`roadmap = <view>`), so item RBAC applies."""

    __tablename__ = "view_members"

    view_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("views.id", ondelete="CASCADE"), primary_key=True
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("work_items.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    # Future explicit ordering; 0 = fetch order for now.
    position: Mapped[int] = mapped_column(Integer, default=0)
    added_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class CardLayoutPreset(Base, TimestampMixin):
    """A named board-card layout in the shared instance library (spec 109).

    Applying a preset COPIES its layout onto the view — a snapshot, never a
    live reference — so editing a preset later cannot silently restyle boards.
    Reads are open to members; writes ride the cardpreset.* atoms.
    """

    __tablename__ = "card_layout_presets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    layout: Mapped[dict[str, Any]] = mapped_column(JSONB)  # the CardLayout wire shape
    position: Mapped[int] = mapped_column(Integer, default=0)
