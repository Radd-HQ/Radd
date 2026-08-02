import uuid
from typing import Any

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from radd.db import Base, TimestampMixin


class View(Base, TimestampMixin):
    """A saved view: a named board/list over an SLQ query (spec 10).

    Ownership + sharing (spec 57): `owner_id` = the creator (full control —
    edit, share, delete). Visibility = owner ∪ `view_shares` grantees (users /
    team members, each at a `ShareLevel`) ∪ every active user when
    `global_access` is set (its value = the level everyone gets). No shares +
    no global_access = private. LEGACY: pre-spec-57 globally-shared views
    have `owner_id` NULL — they're managed via the view.* RBAC atoms instead
    of an owner. `project_id` NULL = all-projects. `query` is SLQ text
    (compile-validated on write against the field registry; '' =
    everything). `group_by`/`swimlane_by` are axis tokens
    (state|assignee|priority|kind|team|cf.<select-key>); they must differ.
    """

    __tablename__ = "views"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    view_type: Mapped[str] = mapped_column(String(20))  # ViewType
    query: Mapped[str] = mapped_column(Text, default="")  # SLQ
    group_by: Mapped[str | None] = mapped_column(Text)  # axis token; None = ungrouped
    swimlane_by: Mapped[str | None] = mapped_column(Text)  # axis token; None = no swimlanes
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

# View shares (spec 57) moved to the generic `access_grants` table (spec 92,
# resource_type="view", access = a ShareLevel). `owner_id` + `global_access` above
# stay on the view — they're not per-subject grants.


class ViewMember(Base, TimestampMixin):
    """Curated view membership (roadmap wave): a hand-picked item pinned to a
    view. Mechanism only — the roadmap surface's Members/All toggle is the
    policy on top, and the `roadmap` SLQ field this module registers is the
    read seam (`/items?q=roadmap = "<view>"`), so membership is queryable on
    ANY item surface, not just the roadmap. Writes ride the spec-57 view edit
    gate (owner/editor); reads are the item dialect, so item RBAC applies.
    """

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
