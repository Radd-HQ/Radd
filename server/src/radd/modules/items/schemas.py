import uuid
from datetime import date
from typing import Any

from pydantic import BaseModel, Field, model_validator

from radd.config import settings
from radd.modules.cycles.types import CycleStatus
from radd.modules.fields.openapi import CUSTOM_FIELDS_MARKER
from radd.modules.itemtypes.schemas import TypeRef
from radd.modules.releases.types import ReleaseStatus
from radd.modules.workflow.schemas import StateRef

from .enums import BulkSkipReason, ItemKind, Priority
from radd.apitypes import UtcDatetime

_custom_fields = Field(default_factory=dict, json_schema_extra={CUSTOM_FIELDS_MARKER: True})


class ParentRef(BaseModel):
    """Compact embed of an item's parent (epic or issue)."""

    id: uuid.UUID
    key: str
    title: str


class CycleRef(BaseModel):
    """Compact embed of the cycle an item is planned into (status is derived)."""

    id: uuid.UUID
    name: str
    status: CycleStatus


class ReleaseRef(BaseModel):
    """Compact embed of the release an item is targeting."""

    id: uuid.UUID
    version: str
    status: ReleaseStatus


class LinkItem(BaseModel):
    """The item on the far end of a dependency link."""

    id: uuid.UUID
    key: str
    title: str


class ItemLinkRead(BaseModel):
    """One dependency edge from the perspective of the item being read."""

    id: uuid.UUID  # the link row id (used by DELETE /items/{id}/links/{link_id})
    link_type: str  # the link-type KEY (spec 91: types are data, not a fixed enum)
    label: str = ""  # directional display name for THIS edge (outward if source, inward if target)
    item: LinkItem


class ItemLinks(BaseModel):
    """An item's dependency links, split by direction (incoming = this item is the target)."""

    outgoing: list[ItemLinkRead] = Field(default_factory=list)
    incoming: list[ItemLinkRead] = Field(default_factory=list)


class ItemClone(BaseModel):
    """POST /items/{id}/clone (RADD-1088). Omitted title -> "Copy of <source>"."""

    title: str | None = Field(default=None, min_length=1, max_length=500)
    include_subtasks: bool = False


class ItemLinkCreate(BaseModel):
    """Create a link to another item — address it by id OR by per-project number.
    `link_type` is a link-type KEY (spec 91), validated against the catalog in the
    service so both built-in and custom types work."""

    target_id: uuid.UUID | None = None
    target_number: int | None = None
    link_type: str = Field(min_length=1, max_length=30)


class UserRef(BaseModel):
    """Compact embed of a user (assignee, comment author)."""

    id: uuid.UUID
    name: str
    # Avatar (spec 34) — colored initials circle, optional emoji override.
    avatar_color: str | None = None
    avatar_emoji: str | None = None


class TeamRef(BaseModel):
    """Compact embed of the team an item is routed to."""

    id: uuid.UUID
    name: str


class ItemCreate(BaseModel):
    project_id: uuid.UUID
    # Explicit key number, for imports that preserve original IDs (Jira TD-48728 ->
    # TD-48728). None = auto-allocate the next number. Must be unused in the project.
    number: int | None = Field(default=None, ge=1)
    title: str = Field(min_length=1, max_length=500)
    description: str = ""
    kind: ItemKind = ItemKind.ISSUE
    type_id: uuid.UUID | None = None  # spec 51 — None = the project's default issue type
    parent_id: uuid.UUID | None = None  # required for subtasks; forbidden for epics
    state_id: uuid.UUID | None = None  # None = the project's default state
    priority: Priority = Priority.NORMAL
    assignee_id: uuid.UUID | None = None
    # None = the acting user (spec 30) — set explicitly when filing on someone's behalf.
    reporter_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    start_date: date | None = None
    target_date: date | None = None
    cycle_id: uuid.UUID | None = None
    release_id: uuid.UUID | None = None  # same project as the item
    flagged: bool = False  # first-class shared flag (spec 24)
    # Story points (spec 70): 0–999, one decimal (DB rounds). None = unestimated.
    estimate_points: float | None = Field(default=None, ge=0, le=999)
    # Import-only (project.manage-gated): preserve the original creation timestamp
    # (naive UTC) so an imported item shows its real age, not the import time.
    created_at: UtcDatetime | None = None
    #: Import only (project.manage), like `created_at`: the issue's real
    #: last-touched time. Omitted on create falls back to `created_at`.
    updated_at: UtcDatetime | None = None
    labels: list[str] = Field(default_factory=list)
    custom_fields: dict[str, Any] = _custom_fields


class ItemUpdate(BaseModel):
    #: Import only (project.manage): restore the source's last-touched time
    #: instead of letting this write stamp it with `now()`.
    updated_at: UtcDatetime | None = None
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    # For the nullable relations/dates: omitted = unchanged, explicit null = clear.
    parent_id: uuid.UUID | None = None
    type_id: uuid.UUID | None = None  # spec 51 — omitted = unchanged, null = clear
    state_id: uuid.UUID | None = None
    priority: Priority | None = None
    assignee_id: uuid.UUID | None = None
    reporter_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    start_date: date | None = None
    target_date: date | None = None
    cycle_id: uuid.UUID | None = None
    release_id: uuid.UUID | None = None
    flagged: bool | None = None  # spec 24 — omitted = unchanged
    # Story points (spec 70): omitted = unchanged, explicit null = clear.
    estimate_points: float | None = Field(default=None, ge=0, le=999)
    labels: list[str] | None = None  # full replacement when provided
    # Merged into existing values; a key set to null clears that field.
    custom_fields: dict[str, Any] | None = Field(
        default=None, json_schema_extra={CUSTOM_FIELDS_MARKER: True}
    )


# --- bulk operations (spec 68) ---

_bulk_ids = Field(min_length=1, max_length=settings.bulk_max_items)


class ItemBulkPatch(BaseModel):
    """The restricted patch a bulk edit may apply. Nullable relations use the
    model_fields_set idiom (omitted = unchanged, explicit null = clear); labels
    are DELTAS (add/remove), not a replacement."""

    state_id: uuid.UUID | None = None
    assignee_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    priority: Priority | None = None
    type_id: uuid.UUID | None = None
    cycle_id: uuid.UUID | None = None
    release_id: uuid.UUID | None = None
    flagged: bool | None = None
    archived: bool | None = None
    add_labels: list[str] | None = None
    remove_labels: list[str] | None = None

    @model_validator(mode="after")
    def _not_empty(self) -> "ItemBulkPatch":
        if not self.model_fields_set:
            raise ValueError("empty patch — set at least one field")
        return self


class ItemBulkUpdate(BaseModel):
    item_ids: list[uuid.UUID] = _bulk_ids
    patch: ItemBulkPatch


class ItemBulkMove(BaseModel):
    item_ids: list[uuid.UUID] = _bulk_ids
    target_project_id: uuid.UUID


class BulkSkipped(BaseModel):
    """One item a bulk operation could not apply to, with the reason."""

    item_id: uuid.UUID
    key: str | None = None
    reason: BulkSkipReason
    detail: str | None = None


class BulkUpdateResult(BaseModel):
    updated: list[uuid.UUID] = Field(default_factory=list)
    skipped: list[BulkSkipped] = Field(default_factory=list)


class BulkMovedItem(BaseModel):
    item_id: uuid.UUID
    old_key: str
    new_key: str
    dropped_fields: list[str] = Field(default_factory=list)


class BulkMoveResult(BaseModel):
    moved: list[BulkMovedItem] = Field(default_factory=list)
    skipped: list[BulkSkipped] = Field(default_factory=list)


class ItemIds(BaseModel):
    """GET /items/ids — the 'select all matching' seam: ids capped at
    settings.bulk_max_items, `total` the true visible count."""

    ids: list[uuid.UUID] = Field(default_factory=list)
    total: int = 0


class ItemCount(BaseModel):
    """GET /items/count (spec 75) — the visible-match count alone; powers the
    dashboard slq_count widgets."""

    total: int = 0


# One rollup batch covers a board/list page of epic cards (spec 76) — mirrors
# the POST /items/sla/batch cap.
ROLLUP_MAX_ITEMS = 200


class ItemRollupRequest(BaseModel):
    """POST /items/rollup — batched epic-progress aggregates. Ids in unreadable
    projects are omitted from the response, never errored (sla/batch idiom)."""

    item_ids: list[uuid.UUID] = Field(max_length=ROLLUP_MAX_ITEMS)


class ItemRollup(BaseModel):
    """Aggregates over ALL of one item's descendants (children + grandchildren,
    each counted once): `done` = done/canceled-category states, `in_progress` =
    in_progress category, points from `estimate_points` (spec 70), time from the
    timelogging module when it's installed (zeros otherwise)."""

    total: int = 0
    done: int = 0
    in_progress: int = 0
    points_total: float = 0
    points_done: float = 0
    estimate_seconds: int = 0
    logged_seconds: int = 0


class ItemRankUpdate(BaseModel):
    """Reorder an item between two neighbours (spec 24): the item lands so that
    `after_id` precedes it and `before_id` follows it. Omit `after_id` to move to
    the top of a bucket, omit `before_id` to move to the bottom."""

    after_id: uuid.UUID | None = None
    before_id: uuid.UUID | None = None


class ItemCapabilities(BaseModel):
    """The ACTOR's per-row verdict (RADD-842). Relations made writability a
    per-ROW fact — `item.update@own` on someone else's issue must read as a
    disabled editor up front (spec 96), never edit-then-error. Attached at the
    API boundary (listing + detail), absent from event payloads (a stream
    consumer has no actor)."""

    can_update: bool
    # State changes ride the update path (state_id is an ItemUpdate field), so
    # today's verdict is can_update's; a separate transition relation would
    # change only this line.
    can_transition: bool
    can_comment: bool


class ItemRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    key: str
    number: int
    kind: ItemKind
    type: TypeRef | None = None  # spec 51 — the issue-type classification
    title: str
    description: str
    state: StateRef
    priority: Priority
    parent: ParentRef | None
    # The epic this item BELONGS TO — itself if it is one, else its parent, else
    # its grandparent (RADD-697; same rule as SLQ's `epic` field). Null for work
    # no epic governs. Carried on every item so a client can group by epic
    # without walking the hierarchy it cannot see.
    epic: ParentRef | None = None
    assignee: UserRef | None
    reporter: UserRef | None = None
    team: TeamRef | None
    start_date: date | None = None
    target_date: date | None = None
    cycle: CycleRef | None = None
    # Cycles the item was previously in (spec 56, closed stints oldest-first) —
    # the carryover trail; queryable as SLQ `past_cycle`.
    past_cycles: list[CycleRef] = Field(default_factory=list)
    release: ReleaseRef | None = None
    flagged: bool = False
    # Story points (spec 70) — always serialized; null when unused (UI gating is
    # the optionality contract, not schema surgery).
    estimate_points: float | None = None
    starred: bool = False  # personal star for the requesting user (spec 24)
    archived_at: UtcDatetime | None = None  # spec 38
    links: ItemLinks = Field(default_factory=ItemLinks)
    child_count: int
    comment_count: int
    labels: list[str]
    custom_fields: dict[str, Any] = _custom_fields
    created_at: UtcDatetime
    updated_at: UtcDatetime
    # RADD-842: the actor's per-row verdict; None on surfaces with no actor
    # (event payloads, imports).
    capabilities: ItemCapabilities | None = None


class HistoryActor(BaseModel):
    """The user who caused a change (from the event's actor_id)."""

    id: uuid.UUID
    name: str


class HistoryEntry(BaseModel):
    """One activity-feed row: an item field change (`changes`) or a related event
    attached to the item (comment/worklog/link) summarized in `detail`."""

    id: int  # the event offset (monotonic, stable sort key)
    at: UtcDatetime
    actor: HistoryActor | None = None
    type: str  # event_type, e.g. "item.created", "item.updated", "comment.created"
    changes: list[dict[str, Any]] = Field(default_factory=list)  # item.updated field diffs
    detail: dict[str, Any] | None = None  # compact payload for related events


class ItemHistory(BaseModel):
    entries: list[HistoryEntry] = Field(default_factory=list)


class ItemLinkSearchResult(BaseModel):
    """A candidate item for the dependency-link typeahead (GET /items/link-search)."""

    id: uuid.UUID
    number: int
    key: str
    title: str
    kind: ItemKind


class SlqValidation(BaseModel):
    """GET /items/slq/validate: a valid (or blank) draft — invalid drafts 422."""

    ok: bool = True
