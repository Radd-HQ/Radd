"""Input schemas for the item MCP tools.

`create_item`/`update_item`/`link_items`/`unlink_items` are LIVE: their
`input_schema_builder`s receive the current custom-field properties (the same
source as OpenAPI) and link-type keys; the static `input_schema` is the same
shape with those projections empty.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from radd.kernel.mcptools import limit_property, object_schema

from .enums import ItemKind, Priority

#: Most-recent comments inlined by get_item (spec 45 result shaping).
GET_ITEM_COMMENTS_TAIL = 10

_SLQ_DOC = (
    "SLQ query text. Grammar: `field op value` clauses joined with AND/OR/NOT and "
    "parentheses, optional `ORDER BY field [ASC|DESC], ...` at the end. "
    "Builtin fields: project (key), state (name), category, kind, priority, assignee "
    "(email|me|none), reporter, team, label, title, key, parent, number, created, "
    "updated, cycle, release, flagged, starred, blocks, blocked, start, target — plus "
    "any custom field by its registry key. Operators: = != ~ (contains) > < >= <=, "
    "IN (a, b), NOT IN, IS EMPTY, IS NOT EMPTY. Quote values with spaces "
    "('In Progress'); `me` = the calling user; `none` = unset relation; dates are "
    "YYYY-MM-DD. Examples: `project = TD AND state != Done ORDER BY priority DESC` · "
    "`assignee = me AND label IN (urgent, farm)` · `title ~ render AND created >= 2026-01-01`."
)

_KIND_VALUES = [kind.value for kind in ItemKind]
_PRIORITY_VALUES = [priority.value for priority in Priority]

#: The plain-date write fields (ISO `YYYY-MM-DD`; null clears on update). One
#: tuple feeds both the schema and the handler's parsing.
DATE_FIELDS = ("start_date", "target_date")


def key_property() -> dict[str, Any]:
    return {"type": "string", "description": "Item key, e.g. TD-42."}


def _link_type_property(keys: Sequence[str]) -> dict[str, Any]:
    """The `type` parameter for the link tools (RADD-739).

    An ENUM when the catalog is known, degrading to a plain string when it is
    not — the same shape spec 114 uses for the project parameter, and for the
    same reason: an agent should not have to guess an instance's vocabulary.
    """
    base: dict[str, Any] = {
        "type": "string",
        "description": "Link type key, e.g. blocks. Link types are studio-defined (spec 91).",
    }
    if keys:
        base["enum"] = sorted(keys)
    return base


def _custom_fields_schema(custom_field_properties: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": dict(custom_field_properties),
        "description": "Studio-defined custom fields by registry key "
        "(this schema is generated live from the field registry).",
    }


def _item_write_properties(custom_field_properties: Mapping[str, Any]) -> dict[str, Any]:
    """The optional write parameters create_item and update_item share. Names in,
    ids resolved server-side (RADD-673) — the tracking workflow needs type,
    parent, estimate and cycle without a REST detour for id lookups."""
    return {
        "description": {"type": "string", "description": "Markdown body."},
        "state": {"type": "string", "description": "Workflow state NAME (project-specific)."},
        "priority": {"type": "string", "enum": _PRIORITY_VALUES},
        "type": {
            "type": "string",
            "description": "Issue type NAME (project-specific, spec 51), e.g. Bug or Feature.",
        },
        "parent": {
            "type": ["string", "null"],
            "description": "Parent item KEY (an epic for an issue, an issue for a subtask); "
            "null clears it (update only).",
        },
        "estimate_points": {
            "type": ["number", "null"],
            "minimum": 0,
            "maximum": 999,
            "description": "Estimate in points; null clears it (update only).",
        },
        "cycle": {
            "type": ["string", "null"],
            "description": "Cycle NAME (cycles span projects); null clears it (update only).",
        },
        "assignee_email": {
            "type": ["string", "null"],
            "description": "Assignee's email; null clears the assignee (update only).",
        },
        "labels": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Full replacement label set (labels are created on demand).",
        },
        **{
            field: {
                "type": ["string", "null"],
                "format": "date",
                "description": f"{field.replace('_', ' ').capitalize()} as YYYY-MM-DD; "
                "null clears it (update only).",
            }
            for field in DATE_FIELDS
        },
        "custom_fields": _custom_fields_schema(custom_field_properties),
    }


# --- the static schemas -------------------------------------------------------


def search_items_schema() -> dict[str, Any]:
    return object_schema(
        {
            "slq": {"type": "string", "description": _SLQ_DOC},
            "limit": limit_property(),
        },
        ["slq"],
    )


def key_only_schema() -> dict[str, Any]:
    """get_item / get_allowed_transitions: the item key and nothing else."""
    return object_schema({"key": key_property()}, ["key"])


def comment_item_schema() -> dict[str, Any]:
    return object_schema(
        {
            "key": key_property(),
            "body": {"type": "string", "description": "Markdown comment body."},
            "internal": {
                "type": "boolean",
                "default": False,
                "description": "Team-only visibility (requires the "
                "internal-comments permission). On a reply, unset means the "
                "thread's own audience; an internal thread makes the reply internal.",
            },
            "reply_to": {
                "type": "string",
                "description": "Reply under one of the item's comments — its id, as get_item "
                "lists them. Replies are one level deep.",
            },
            "is_thread": {
                "type": "boolean",
                "description": "Start a resolvable discussion instead of an ordinary comment. Not valid with reply_to.",
            },
            "unresolve": {
                "type": "boolean",
                "description": "With reply_to on a resolved thread: reopen it in the same write. "
                "Without it, a reply leaves a resolved thread resolved.",
            },
        },
        ["key", "body"],
    )


def transition_item_schema() -> dict[str, Any]:
    return object_schema(
        {
            "key": key_property(),
            "state": {"type": "string", "description": "Target state name."},
        },
        ["key", "state"],
    )


def clone_item_schema() -> dict[str, Any]:
    return object_schema(
        {
            "key": key_property(),
            "title": {"type": "string", "description": "Clone's title; omitted = 'Copy of <source>'."},
            "include_subtasks": {"type": "boolean", "default": False},
        },
        ["key"],
    )


def move_item_schema() -> dict[str, Any]:
    return object_schema(
        {
            "key": key_property(),
            "target_project_key": {"type": "string", "description": "Destination project key."},
        },
        ["key", "target_project_key"],
    )


def convert_item_schema() -> dict[str, Any]:
    return object_schema(
        {
            "key": key_property(),
            "kind": {"type": "string", "enum": _KIND_VALUES},
            "parent": {"type": ["string", "null"], "description": "New parent's key; null = detach."},
        },
        ["key", "kind"],
    )


def merge_item_schema() -> dict[str, Any]:
    return object_schema(
        {
            "source_key": {"type": "string", "description": "The duplicate being closed."},
            "target_key": {"type": "string", "description": "The survivor."},
        },
        ["source_key", "target_key"],
    )


# --- the LIVE schemas (input_schema_builder targets) --------------------------


def create_item_schema(
    *,
    custom_field_properties: Mapping[str, Any] | None = None,
    **_: Any,
) -> dict[str, Any]:
    return object_schema(
        {
            "project_key": {"type": "string", "description": "Project key, e.g. TD."},
            "title": {"type": "string"},
            "kind": {
                "type": "string",
                "enum": _KIND_VALUES,
                "default": ItemKind.ISSUE.value,
            },
            **_item_write_properties(custom_field_properties or {}),
        },
        ["project_key", "title"],
    )


def update_item_schema(
    *,
    custom_field_properties: Mapping[str, Any] | None = None,
    **_: Any,
) -> dict[str, Any]:
    return object_schema(
        {
            "key": key_property(),
            "title": {"type": "string"},
            **_item_write_properties(custom_field_properties or {}),
        },
        ["key"],
    )


def link_items_schema(*, link_types: Sequence[str] = (), **_: Any) -> dict[str, Any]:
    return object_schema(
        {
            "from_key": {
                "type": "string",
                "description": "The SOURCE item's key, e.g. TD-42 — the one that "
                "blocks/relates/duplicates.",
            },
            "to_key": {"type": "string", "description": "The TARGET item's key."},
            "type": _link_type_property(link_types),
        },
        ["from_key", "to_key", "type"],
    )


def unlink_items_schema(*, link_types: Sequence[str] = (), **_: Any) -> dict[str, Any]:
    return object_schema(
        {
            "from_key": {"type": "string", "description": "The SOURCE item's key."},
            "to_key": {"type": "string", "description": "The TARGET item's key."},
            "type": _link_type_property(link_types),
        },
        ["from_key", "to_key", "type"],
    )
