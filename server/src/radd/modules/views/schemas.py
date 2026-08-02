import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .types import AXIS_TOKEN_PATTERN, ShareLevel, ViewType
from radd.apitypes import UtcDatetime


def _validate_view_type(value: str) -> str:
    """A view_type is valid iff it is a builtin `ViewType` OR a plugin-contributed
    key in the kernel's `registries.view_types` (spec 94). Imported lazily to avoid
    an import cycle (kernel ← plugins ← this module)."""
    from radd.kernel import registries

    if value in {t.value for t in ViewType} or value in registries.view_types:
        return value
    raise ValueError(f"unknown view type '{value}'")

# SOFT WIP limits (spec 76): {state_id: int>=1} — non-positive values 422 here;
# unknown state ids on PROJECT-scoped views 409 in the service (an all-projects
# board's buckets are name-keyed, so any UUID key is accepted there).
WipLimits = dict[uuid.UUID, Annotated[int, Field(ge=1)]]

# Axis token: state|assignee|priority|kind|team or cf.<key> (select-type registry
# field — semantic checks incl. swimlane_by != group_by live in the service -> 409).
_axis_field = Field(default=None, pattern=AXIS_TOKEN_PATTERN)


# --- Board-card layout (spec 109) --------------------------------------------
# An 8-column grid; the client renders each occupied row as a flex lane (span is
# a width hint — exact for growable attrs, floor-of-natural-width for chips).
CARD_GRID_COLS = 8
CARD_LAYOUT_MAX_ROWS = 8
CARD_LAYOUT_MAX_CELLS = 24


class CardLayoutCell(BaseModel):
    """One placed attribute: `title`, a builtin id, or `cf.<key>`. Ids are
    validated loosely (length only) — a departed custom field must degrade to
    an empty cell, not brick the view. Semantic checks (one title, no same-row
    overlap, col+span bounds) live in the service -> 409."""

    attr: str = Field(min_length=1, max_length=80)
    row: int = Field(ge=0, lt=CARD_LAYOUT_MAX_ROWS)
    col: int = Field(ge=0, lt=CARD_GRID_COLS)
    span: int = Field(default=1, ge=1, le=CARD_GRID_COLS)
    align: Literal["start", "end"] = "start"


class CardLayout(BaseModel):
    """The stored card shape (views.card_layout / preset layouts). Row 0 is the
    header lane (inline with key/star/flag); rows >= 1 are body lanes. The
    fixed chrome (checkbox, kind/type, key, star, flag) is never a cell."""

    v: Literal[1] = 1
    cells: list[CardLayoutCell] = Field(max_length=CARD_LAYOUT_MAX_CELLS)
    max_labels: int = Field(default=3, ge=0, le=99)


class CardPresetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    layout: CardLayout
    position: int = Field(default=0, ge=0)


class CardPresetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    layout: CardLayout | None = None
    position: int | None = Field(default=None, ge=0)


class CardPresetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    layout: CardLayout
    position: int
    created_at: UtcDatetime
    updated_at: UtcDatetime


class QuickFilter(BaseModel):
    """One clickable filter chip on a view — active chips AND into the query.
    Conditions only (no ORDER BY); compile-validated on write."""

    name: str = Field(min_length=1, max_length=60)
    query: str = Field(min_length=1, max_length=500)


# One counts batch covers a sidebar of queue badges (spec 64) — no N+1 loops.
VIEW_COUNTS_MAX_VIEWS = 50


class ViewCountsRequest(BaseModel):
    """POST /views/counts — batched membership counts for sidebar badges.
    Invisible/unknown ids are omitted from the response, never errored."""

    view_ids: list[uuid.UUID] = Field(max_length=VIEW_COUNTS_MAX_VIEWS)
    # Extra SLQ ANDed onto every view's own query (the dashboard-wide filter
    # reaching view-count widgets). A non-compiling extra omits the count,
    # same as a stale stored query.
    extra_q: str | None = None


class ViewShareEntry(BaseModel):
    """One sharing grant to write (spec 57): exactly one of user_id/team_id."""

    user_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    level: ShareLevel = ShareLevel.VIEWER

    @model_validator(mode="after")
    def _one_subject(self) -> "ViewShareEntry":
        if (self.user_id is None) == (self.team_id is None):
            raise ValueError("exactly one of user_id/team_id is required")
        return self


class ViewSharingUpdate(BaseModel):
    """PUT /views/{id}/sharing — the view's PUBLIC access level (spec 92; owner-gated).
    Per-subject shares are managed through the generic /grants API now."""

    global_access: ShareLevel | None = None


class ViewTransfer(BaseModel):
    """POST /views/{id}/transfer — reassign `owner_id`. The previous owner is
    kept on as an editor grantee (no accidental lockout; the new owner decides)."""

    user_id: uuid.UUID


class ViewCreate(BaseModel):
    project_id: uuid.UUID | None = None  # None = global (spanning every project)
    name: str = Field(min_length=1, max_length=100)
    # Builtin `ViewType` value OR a plugin-registered key (kernel registries.view_types).
    view_type: str

    @field_validator("view_type")
    @classmethod
    def _check_view_type(cls, value: str) -> str:
        return _validate_view_type(value)

    # SLQ (spec 10); '' = every item in scope. Compile-validated on write -> 422
    # {detail, position} on error.
    query: str = ""
    group_by: str | None = _axis_field
    swimlane_by: str | None = _axis_field
    # Cycle-name regex for the `cycle` axis header set (specs 23/56); None/'' = all.
    cycle_filter: str | None = Field(default=None, max_length=200)
    quick_filters: list[QuickFilter] = Field(default_factory=list, max_length=10)
    # Soft WIP limits for state-axis board columns (spec 76); None = no limits.
    wip_limits: WipLimits | None = None
    # Spec 108: ordered list-surface columns (builtin ids or `cf.<key>`);
    # None = the view type's default set.
    columns: list[str] | None = Field(default=None, max_length=16)
    # Spec 109: the board-card layout; None = the type's default card.
    card_layout: CardLayout | None = None
    # Sharing at birth (spec 57). `shared` is the pre-57 alias: True and no
    # explicit global_access -> global_access = viewer.
    global_access: ShareLevel | None = None
    shares: list[ViewShareEntry] = Field(default_factory=list, max_length=50)
    shared: bool = False
    position: int = Field(default=0, ge=0)


class ViewUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    # Builtin `ViewType` value OR a plugin-registered key; None/omitted = unchanged.
    view_type: str | None = None
    query: str | None = None

    @field_validator("view_type")
    @classmethod
    def _check_view_type(cls, value: str | None) -> str | None:
        return value if value is None else _validate_view_type(value)
    # Omitted = unchanged, explicit null = clear the axis.
    group_by: str | None = _axis_field
    swimlane_by: str | None = _axis_field
    # Omitted = unchanged, explicit null/'' = all cycles (spec 23).
    cycle_filter: str | None = Field(default=None, max_length=200)
    quick_filters: list[QuickFilter] | None = Field(default=None, max_length=10)
    # Omitted = unchanged, explicit null = clear every limit (model_fields_set).
    wip_limits: WipLimits | None = None
    # Omitted = unchanged, explicit null = back to the type's defaults (spec 108).
    columns: list[str] | None = Field(default=None, max_length=16)
    # Omitted = unchanged, explicit null = back to the type's default card (spec 109).
    card_layout: CardLayout | None = None
    position: int | None = Field(default=None, ge=0)


class ShareUserRef(BaseModel):
    id: uuid.UUID
    name: str


class ShareTeamRef(BaseModel):
    id: uuid.UUID
    name: str


class ViewShareRead(BaseModel):
    id: uuid.UUID
    level: ShareLevel
    user: ShareUserRef | None = None
    team: ShareTeamRef | None = None


class ViewRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    name: str
    # The stored view_type string (a builtin `ViewType` value or a plugin key).
    view_type: str
    query: str
    group_by: str | None
    swimlane_by: str | None
    cycle_filter: str | None
    quick_filters: list[QuickFilter]
    # Soft WIP limits (spec 76): {state_id: limit}; None = no limits set.
    wip_limits: dict[uuid.UUID, int] | None = None
    # Spec 108: ordered list-surface columns; None = the type's default set.
    columns: list[str] | None = None
    # Spec 109: the board-card layout; None = the type's default card.
    card_layout: CardLayout | None = None
    owner_id: uuid.UUID | None
    # Sharing (spec 57): who owns it, what every active user gets, and the
    # explicit grants; `shared` = visible beyond the owner (any of the above).
    owner: ShareUserRef | None = None
    global_access: ShareLevel | None = None
    shares: list[ViewShareRead] = Field(default_factory=list)
    shared: bool
    # Per-ACTOR capabilities, computed server-side (the client never re-derives
    # team membership): edit = change the definition; manage = sharing + delete.
    can_edit: bool = False
    can_manage: bool = False
    position: int
    # Ready-to-append `GET /items?<query_string>` composition: `q=<urlencoded SLQ>`
    # (omitted when the query is empty) + `project_id=<id>` when project-scoped.
    query_string: str
    created_at: UtcDatetime
    updated_at: UtcDatetime
