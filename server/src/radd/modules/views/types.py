from enum import StrEnum


class ViewType(StrEnum):
    BOARD = "board"
    LIST = "list"
    # Backlog & cycle planning: rendered as cycle-grouped sections with
    # cross-bucket drag — the group_by/swimlane_by axes are ignored (cycle implied).
    PLANNING = "planning"
    # Triage queue (spec 64): a fixed-column list skin (reporter/age/always-on SLA,
    # urgency-ordered client-side) — the axes are ignored like planning. Sidebar
    # badges come from POST /views/counts.
    QUEUE = "queue"
    # Roadmap/Gantt (spec 79): the spec-77/78 timeline rendered as an ordinary
    # saved view — axes stored-but-ignored like planning/queue; the client
    # fetches EVERY page of the view query (no Load-more) so bars + the
    # Unscheduled tray always show the full match set.
    ROADMAP = "roadmap"


class ViewAxis(StrEnum):
    """Builtin grouping axes for rendering a view (board columns / list sections /
    swimlane rows). Select-type custom fields join the domain as `cf.<key>` tokens
    (validated against the registry in views/service.py)."""

    STATE = "state"
    ASSIGNEE = "assignee"
    PRIORITY = "priority"
    KIND = "kind"
    TEAM = "team"
    CYCLE = "cycle"  # buckets = workspace cycles (+ a Backlog bucket); see spec 23


# Axis token prefix addressing a select-type custom field by registry key.
CF_AXIS_PREFIX = "cf."

# Full token shape (pydantic-validates on write; semantic checks live in the service).
# Key charset mirrors fields.schemas.FieldDefinitionCreate.
AXIS_TOKEN_PATTERN = rf"^({'|'.join(axis.value for axis in ViewAxis)}|cf\.[a-z][a-z0-9_]{{0,49}})$"


class ShareLevel(StrEnum):
    """Access a share grant (or `views.global_access`) confers (spec 57).
    `owner` grants FULL control (edit + manage sharing + delete + transfer) —
    co-ownership; `views.owner_id` stays the single accountable owner and can
    be reassigned via POST /views/{id}/transfer."""

    VIEWER = "viewer"
    EDITOR = "editor"
    OWNER = "owner"


class ViewEvent(StrEnum):
    CREATED = "view.created"
    UPDATED = "view.updated"
    DELETED = "view.deleted"
    # Card-layout preset library (spec 109).
    CARD_PRESET_CREATED = "view.card_preset.created"
    CARD_PRESET_UPDATED = "view.card_preset.updated"
    CARD_PRESET_DELETED = "view.card_preset.deleted"


class ViewEntity(StrEnum):
    VIEW = "view"
    CARD_PRESET = "card_preset"
