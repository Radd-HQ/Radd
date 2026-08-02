"""The MCP tool catalog (spec 45) — tools/list payload generation.

`build_catalog` is pure (testable with a stubbed registry); `live_catalog`
feeds it the live field-registry projection — the SAME source as OpenAPI — so
studio-defined custom fields appear as documented `custom_fields` properties
automatically. Doc tools are appended only when the pages module is live
(feature-detected in pages_bridge).
"""

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.fields import openapi as fields_openapi, service as fields_service
from radd.modules.items.enums import ItemKind, Priority
from radd.modules.releases.types import ReleaseStatus

from .pages_bridge import pages_available
from .types import GET_ITEM_COMMENTS_TAIL, SEARCH_LIMIT_DEFAULT, SEARCH_LIMIT_MAX, McpTool

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


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


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
        "custom_fields": _custom_fields_schema(custom_field_properties),
    }


def build_catalog(
    custom_field_properties: Mapping[str, Any],
    *,
    include_pages: bool,
    link_types: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """The tools/list payload. Pure: the registry projection is passed in.

    `link_types` (RADD-739) enumerates the instance's ACTUAL link-type keys.
    They are user-definable (spec 91), so a free-string parameter would have an
    agent guessing whether this instance says `blocks`, `depends_on`, or
    something a studio invented — the same argument spec 114 already makes for
    the project parameter.
    """
    write = _item_write_properties(custom_field_properties)
    key_property = {"type": "string", "description": "Item key, e.g. TD-42."}
    limit_property = {
        "type": "integer",
        "minimum": 1,
        "maximum": SEARCH_LIMIT_MAX,
        "default": SEARCH_LIMIT_DEFAULT,
    }
    catalog = [
        {
            "name": McpTool.SEARCH_ITEMS.value,
            "description": "Search work items with an SLQ query (results are RBAC-scoped "
            "to projects the authenticated principal may read).",
            "inputSchema": _schema(
                {
                    "slq": {"type": "string", "description": _SLQ_DOC},
                    "limit": limit_property,
                },
                ["slq"],
            ),
        },
        {
            "name": McpTool.FIND_ITEMS.value,
            "description": "Find work items by text MEANING, not just keywords: hybrid "
            "full-text + semantic retrieval (when the instance has semantic search "
            "configured; plain full-text otherwise). Use this for 'issues about X' "
            "questions; use search_items with SLQ for structured filters.",
            "inputSchema": _schema(
                {
                    "query": {
                        "type": "string",
                        "description": "Plain-language description of what to find.",
                    },
                    "limit": limit_property,
                },
                ["query"],
            ),
        },
        {
            "name": McpTool.LINK_ITEMS.value,
            "description": "Link two work items — e.g. one blocks another. Dependency "
            "links are how a plan records what has to happen before what; without "
            "them the ordering survives only as prose in a description.",
            "inputSchema": _schema(
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
            ),
        },
        {
            "name": McpTool.UNLINK_ITEMS.value,
            "description": "Remove a link between two work items.",
            "inputSchema": _schema(
                {
                    "from_key": {"type": "string", "description": "The SOURCE item's key."},
                    "to_key": {"type": "string", "description": "The TARGET item's key."},
                    "type": _link_type_property(link_types),
                },
                ["from_key", "to_key", "type"],
            ),
        },
        {
            "name": McpTool.GET_ITEM.value,
            "description": "Fetch one work item by key: full detail including custom "
            f"fields inline, plus the {GET_ITEM_COMMENTS_TAIL} most recent comments.",
            "inputSchema": _schema({"key": key_property}, ["key"]),
        },
        {
            "name": McpTool.CREATE_ITEM.value,
            "description": "Create a work item in a project (addressed by project key).",
            "inputSchema": _schema(
                {
                    "project_key": {"type": "string", "description": "Project key, e.g. TD."},
                    "title": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": _KIND_VALUES,
                        "default": ItemKind.ISSUE.value,
                    },
                    **write,
                },
                ["project_key", "title"],
            ),
        },
        {
            "name": McpTool.UPDATE_ITEM.value,
            "description": "Update fields of an existing work item (omitted fields are "
            "unchanged; custom_fields merge into existing values).",
            "inputSchema": _schema(
                {"key": key_property, "title": {"type": "string"}, **write}, ["key"]
            ),
        },
        {
            "name": McpTool.COMMENT_ITEM.value,
            "description": "Add a comment to a work item.",
            "inputSchema": _schema(
                {
                    "key": key_property,
                    "body": {"type": "string", "description": "Markdown comment body."},
                    "internal": {
                        "type": "boolean",
                        "default": False,
                        "description": "Team-only visibility (requires the "
                        "internal-comments permission).",
                    },
                },
                ["key", "body"],
            ),
        },
        {
            "name": McpTool.LIST_PROJECTS.value,
            "description": "List every project on this Radd instance.",
            "inputSchema": _schema({}),
        },
    ]
    if include_pages:
        catalog += [
            {
                "name": McpTool.GET_PAGE.value,
                "description": "Fetch one wiki page by id (full markdown body).",
                "inputSchema": _schema(
                    {"id": {"type": "string", "description": "Doc page id (UUID)."}}, ["id"]
                ),
            },
            {
                "name": McpTool.SEARCH_PAGES.value,
                "description": "Full-text search over wiki pages (title + body), ranked.",
                "inputSchema": _schema(
                    {
                        "query": {"type": "string", "description": "Search terms."},
                        "limit": limit_property,
                    },
                    ["query"],
                ),
            },
        ]
    key_prop = {"type": "string", "description": "Item key, e.g. TD-42."}
    project_prop = {"type": "string", "description": "Project key, e.g. TD."}
    # --- spec 114 families. Each appears only for a key that may execute it; the
    # filter (requirements.visible_catalog) reads the same permission engine the
    # call itself does, so the catalog cannot drift from the enforcement.
    catalog += [
        {
            "name": McpTool.GET_ALLOWED_TRANSITIONS.value,
            "description": "Which workflow states this item may move to right now, and for "
            "the ones it may not, WHY (spec-107 transition guards).",
            "inputSchema": _schema({"key": key_prop}, ["key"]),
        },
        {
            "name": McpTool.TRANSITION_ITEM.value,
            "description": "Move an item to a workflow state by NAME. A guard refusal comes "
            "back as the reason text, not a bare error.",
            "inputSchema": _schema(
                {"key": key_prop, "state": {"type": "string", "description": "Target state name."}},
                ["key", "state"],
            ),
        },
        {
            "name": McpTool.LOG_WORK.value,
            "description": "Log time against an item.",
            "inputSchema": _schema(
                {
                    "key": key_prop,
                    "time_spent": {"type": "string", "description": "Jira-style, e.g. '2h 30m'."},
                    "worked_on": {"type": "string", "description": "ISO date; defaults to today."},
                    "category": {
                        "type": "string",
                        "description": "Work category NAME, e.g. Development (RADD-673).",
                    },
                    "note": {"type": "string"},
                },
                ["key", "time_spent"],
            ),
        },
        {
            "name": McpTool.LIST_WORKLOGS.value,
            "description": "Time entries, filtered with the WORKLOG SLQ dialect "
            "(author, category, worked_on, time, note, and issue.<field> delegated to items).",
            "inputSchema": _schema(
                {
                    "slq": {"type": "string"},
                    "start": {"type": "string", "description": "ISO date; defaults to 30 days back."},
                    "end": {"type": "string", "description": "ISO date; defaults to today."},
                    "limit": limit_property,
                },
                [],
            ),
        },
        {
            "name": McpTool.LIST_RELEASES.value,
            "description": "Releases/versions in a project, with their status.",
            "inputSchema": _schema({"project_key": project_prop}, ["project_key"]),
        },
        {
            "name": McpTool.CREATE_RELEASE.value,
            "description": "Create a release/version in a project.",
            "inputSchema": _schema(
                {
                    "project_key": project_prop,
                    "version": {"type": "string", "description": "e.g. 0.3.0"},
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": [status.value for status in ReleaseStatus],
                        "description": "planned (default) or released — released stamps "
                        "released_at server-side (RADD-673).",
                    },
                },
                ["project_key", "version"],
            ),
        },
        {
            "name": McpTool.SWEEP_RELEASE.value,
            "description": "Ship everything waiting (spec 112): move every item in the "
            "'waiting for release' state into the shipped state with this release set. "
            "The same operation a published Forgejo release performs, on demand.",
            "inputSchema": _schema(
                {
                    "project_key": project_prop,
                    "version": {"type": "string", "description": "Release version to sweep into."},
                },
                ["project_key", "version"],
            ),
        },
        {
            "name": McpTool.SET_ITEM_RELEASE.value,
            "description": "Set (or clear) the release an item ships in.",
            "inputSchema": _schema(
                {
                    "key": key_prop,
                    "version": {
                        "type": ["string", "null"],
                        "description": "Release version; null clears it.",
                    },
                },
                ["key"],
            ),
        },
        {
            "name": McpTool.LIST_USERS.value,
            "description": "Directory of accounts (admin).",
            "inputSchema": _schema(
                {"q": {"type": "string", "description": "Substring of email or name."},
                 "limit": limit_property},
                [],
            ),
        },
        {
            "name": McpTool.LIST_SERVICE_ACCOUNTS.value,
            "description": "Service accounts and their key counts (admin).",
            "inputSchema": _schema({}, []),
        },
        {
            "name": McpTool.CREATE_SERVICE_ACCOUNT.value,
            "description": "Create a service account — a principal that authenticates by API "
            "key only. Keys are minted separately (admin).",
            "inputSchema": _schema(
                {"name": {"type": "string"}, "description": {"type": "string"}}, ["name"]
            ),
        },
    ]
    return catalog


def registry_catalog(builtin_names: frozenset[str]) -> list[dict[str, Any]]:
    """Plugin-contributed tools (RADD-640), read live from the kernel registry so
    a disabled plugin's tools vanish with it. A name colliding with a builtin is
    skipped: the dispatcher resolves builtins first, so listing the plugin's
    schema would advertise a tool that can never run."""
    from radd.kernel import registries  # deferred: the kernel must not be a hard import cycle

    return [
        {"name": spec.name, "description": spec.description, "inputSchema": dict(spec.input_schema)}
        for spec in registries.mcp_tools.values()
        if spec.name not in builtin_names
    ]


async def live_catalog(session: AsyncSession, user: Any = None) -> list[dict[str, Any]]:
    """build_catalog fed from the live registry (same projection as OpenAPI), plus
    plugin-contributed tools (RADD-640), then NARROWED to what this principal may
    execute (spec 114).

    `user=None` returns the whole catalog — the shape tests and the OpenAPI
    projection want the full surface, and an unauthenticated MCP request never
    reaches here (the router 401s first).
    """
    fields_openapi.refresh(await fields_service.list_fields(session))
    from radd.modules.linktypes import service as linktypes_service

    catalog = build_catalog(
        fields_openapi.schema_cache.properties,
        include_pages=pages_available(),
        link_types=[definition.key for definition in await linktypes_service.list_types(session)
                    if not definition.auto_managed],
    )
    catalog += registry_catalog(frozenset(tool["name"] for tool in catalog))
    if user is None:
        return catalog
    from .requirements import visible_catalog  # deferred: requirements imports auth

    return await visible_catalog(session, user, catalog)
