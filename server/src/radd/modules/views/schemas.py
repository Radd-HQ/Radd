from radd.modules.access.schemas import SharedGrantEdits

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

# {state_id: int>=1}; unknown state ids on project-scoped views 409 in the service.
WipLimits = dict[uuid.UUID, Annotated[int, Field(ge=1)]]

# A ViewAxis value or cf.<key>; semantic checks (select type, differ) 409 in the service.
_axis_field = Field(default=None, pattern=AXIS_TOKEN_PATTERN)


# --- Board-card layout (spec 109) --------------------------------------------
# An 8-column grid; the client renders each occupied row as a flex lane (span is
# a width hint — exact for growable attrs, floor-of-natural-width for chips).
CARD_GRID_COLS = 8
CARD_LAYOUT_MAX_ROWS = 8
CARD_LAYOUT_MAX_CELLS = 24


class CardLayoutCell(BaseModel):
    """One placed attribute: `title`, a builtin id, or `cf.<key>` — loosely validated
    (length only) so a departed custom field degrades to an empty cell."""

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


# One counts batch covers a sidebar section of badges (spec 64) — no N+1 loops.
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
    """One share to write: exactly one of user_id/team_id/group_id."""

    user_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    level: ShareLevel = ShareLevel.VIEWER

    @model_validator(mode="after")
    def _one_subject(self) -> "ViewShareEntry":
        named = [x for x in (self.user_id, self.team_id, self.group_id) if x is not None]
        if len(named) != 1:
            raise ValueError("exactly one of user_id/team_id/group_id is required")
        return self


class ViewSharingUpdate(BaseModel):
    """PUT /views/{id}/sharing — the public access level; per-subject grants go through /grants."""

    global_access: ShareLevel | None = None


class ViewTransfer(BaseModel):
    """POST /views/{id}/transfer — reassign `owner_id`. The previous owner is
    kept on as an editor grantee (no accidental lockout; the new owner decides)."""

    user_id: uuid.UUID


#: RADD-855: a per-view bucket order — keys only, capped, loosely validated
#: (the card_layout idiom: departed keys are ignored at render).
_bucket_order_field = Field(default=None, max_length=100)


def _validate_bucket_order(value: list[str] | None) -> list[str] | None:
    if value is None:
        return None
    cleaned = [str(key)[:200] for key in value if str(key).strip()]
    return cleaned or None


class ViewCreate(BaseModel):
    project_id: uuid.UUID | None = None  # None = all projects
    name: str = Field(min_length=1, max_length=100)
    view_type: str  # a builtin ViewType value or a plugin key

    @field_validator("view_type")
    @classmethod
    def _check_view_type(cls, value: str) -> str:
        return _validate_view_type(value)

    query: str = ""  # SLQ ('' = every item in scope); compile errors 422 {detail, position}
    group_by: str | None = _axis_field
    swimlane_by: str | None = _axis_field
    cycle_filter: str | None = Field(default=None, max_length=200)  # cycle-name regex; None/'' = all
    quick_filters: list[QuickFilter] = Field(default_factory=list, max_length=10)
    wip_limits: WipLimits | None = None
    columns: list[str] | None = Field(default=None, max_length=16)  # None = the type's defaults
    card_layout: CardLayout | None = None  # None = the type's default card
    column_order: list[str] | None = _bucket_order_field
    swimlane_order: list[str] | None = _bucket_order_field
    collapse_empty_columns: bool = False
    hidden_columns: list[str] | None = _bucket_order_field
    global_access: ShareLevel | None = None  # what every active user gets; non-None needs view.create
    shares: list[ViewShareEntry] = Field(default_factory=list, max_length=50)
    position: int = Field(default=0, ge=0)


class ViewUpdate(BaseModel):
    """PATCH: an omitted field is unchanged. An explicit null clears a nullable
    setting (axes, cycle_filter, wip_limits, columns, card_layout, bucket orders,
    hidden_columns) back to its default; `model_fields_set` tells the two apart."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    view_type: str | None = None
    query: str | None = None

    @field_validator("view_type")
    @classmethod
    def _check_view_type(cls, value: str | None) -> str | None:
        return value if value is None else _validate_view_type(value)
    group_by: str | None = _axis_field
    swimlane_by: str | None = _axis_field
    cycle_filter: str | None = Field(default=None, max_length=200)
    quick_filters: list[QuickFilter] | None = Field(default=None, max_length=10)
    wip_limits: WipLimits | None = None
    columns: list[str] | None = Field(default=None, max_length=16)
    card_layout: CardLayout | None = None
    column_order: list[str] | None = _bucket_order_field
    swimlane_order: list[str] | None = _bucket_order_field
    collapse_empty_columns: bool | None = None
    hidden_columns: list[str] | None = _bucket_order_field
    position: int | None = Field(default=None, ge=0)


class ShareUserRef(BaseModel):
    id: uuid.UUID
    name: str


class ShareTeamRef(BaseModel):
    id: uuid.UUID
    name: str


class ShareGroupRef(BaseModel):
    """One directory group named by a share (RADD-832)."""

    id: uuid.UUID
    name: str


class ViewShareRead(BaseModel):
    id: uuid.UUID
    level: ShareLevel
    user: ShareUserRef | None = None
    team: ShareTeamRef | None = None
    group: ShareGroupRef | None = None


class ViewRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    name: str
    view_type: str  # stored as-is: a plugin key is not a ViewType member
    query: str
    group_by: str | None
    swimlane_by: str | None
    cycle_filter: str | None
    quick_filters: list[QuickFilter]
    wip_limits: dict[uuid.UUID, int] | None = None
    columns: list[str] | None = None
    card_layout: CardLayout | None = None
    column_order: list[str] | None = _bucket_order_field
    swimlane_order: list[str] | None = _bucket_order_field
    collapse_empty_columns: bool = False
    hidden_columns: list[str] | None = None
    owner_id: uuid.UUID | None
    owner: ShareUserRef | None = None
    global_access: ShareLevel | None = None
    shares: list[ViewShareRead] = Field(default_factory=list)
    # Visible beyond the owner (public level, grants, or a seeded owner-less view).
    shared: bool
    # Per-actor, computed server-side: edit = the definition; manage = sharing + delete.
    can_edit: bool = False
    can_manage: bool = False
    position: int
    # Append to `GET /items?`: q=<SLQ> (when set) + project_id (when scoped).
    query_string: str
    created_at: UtcDatetime
    updated_at: UtcDatetime


class ViewSave(BaseModel):
    """One definition/sharing/ownership transaction; omitted sections stay intact."""

    definition: ViewUpdate | None = None
    sharing: ViewSharingUpdate | None = None
    grants: SharedGrantEdits | None = None
    transfer_to: uuid.UUID | None = None
    expected_owner_id: uuid.UUID | None
    expected_global_access: ShareLevel | None
