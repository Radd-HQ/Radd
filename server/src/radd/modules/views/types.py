from enum import StrEnum


class ViewType(StrEnum):
    BOARD = "board"
    LIST = "list"
    # Backlog & cycle planning: rendered as cycle-grouped sections with
    # cross-bucket drag — the group_by/swimlane_by axes are ignored (cycle implied).
    PLANNING = "planning"
    # Timeline/Gantt; axes stored but ignored, like planning.
    ROADMAP = "roadmap"


class ViewAxis(StrEnum):
    """Builtin grouping axes for rendering a view (board columns / list sections /
    swimlane rows). Select-type custom fields join the domain as `cf.<key>` tokens
    (validated against the registry in views/service.py)."""

    STATE = "state"
    # The category tier above states (bucketed client-side via states' category_key).
    STATE_CATEGORY = "state_category"
    ASSIGNEE = "assignee"
    PRIORITY = "priority"
    KIND = "kind"
    TEAM = "team"
    CYCLE = "cycle"  # buckets = cycles (+ a Backlog bucket)
    # Buckets = the projects the rows live in (RADD-1493) — the lanes of an
    # all-projects board of one epic. Keyed by project id, labelled by key.
    PROJECT = "project"
    # Buckets = epics present in the result (+ No epic). The item's epic is the
    # server's rule (`ItemRead.epic`), so grouping never invents a second one.
    EPIC = "epic"


# Axis token prefix addressing a select-type custom field by registry key.
CF_AXIS_PREFIX = "cf."

# Full token shape (pydantic-validates on write; semantic checks live in the service).
# Key charset mirrors fields.schemas.FieldDefinitionCreate.
AXIS_TOKEN_PATTERN = rf"^({'|'.join(axis.value for axis in ViewAxis)}|cf\.[a-z][a-z0-9_]{{0,49}})$"


class ShareLevel(StrEnum):
    """What a share grant (or `views.global_access`) confers. `owner` = co-ownership
    (edit, share, delete, transfer); `owner_id` stays the one accountable owner."""

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
