"""The MCP tool catalog (spec 45): orders, renders and filters the `McpToolSpec`s owner
modules contribute (RADD-889). `build_catalog` is pure: the live projections (custom-field
properties — the OpenAPI source — and link-type keys) are passed in to each spec's
`input_schema_builder`. A tool whose owner is absent or disabled drops out."""

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from radd.kernel import registries
from radd.kernel.specs import McpToolSpec
from radd.modules.fields import openapi as fields_openapi, service as fields_service

from .types import McpTool

#: The builtin tools in their spec-45/114 wire order. Only order and the builtin/plugin
#: split live here (`registry_catalog` skips these names); the entries are the registry's.
CATALOG_ORDER: tuple[McpTool, ...] = (
    McpTool.SEARCH_ITEMS,
    McpTool.FIND_ITEMS,
    McpTool.LINK_ITEMS,
    McpTool.UNLINK_ITEMS,
    McpTool.GET_ITEM,
    McpTool.CREATE_ITEM,
    McpTool.UPDATE_ITEM,
    McpTool.COMMENT_ITEM,
    McpTool.LIST_PROJECTS,
    McpTool.UPDATE_PROJECT,
    McpTool.DELETE_PROJECT,
    McpTool.GET_PAGE,
    McpTool.SEARCH_PAGES,
    McpTool.CREATE_PAGE,
    McpTool.UPDATE_PAGE,
    McpTool.MOVE_PAGE,
    # --- spec 114 families: listed only for a key that may run them (visible_catalog).
    McpTool.GET_ALLOWED_TRANSITIONS,
    McpTool.TRANSITION_ITEM,
    McpTool.LOG_WORK,
    McpTool.UPDATE_WORKLOG,
    McpTool.DELETE_WORKLOG,
    McpTool.LIST_WORKLOGS,
    McpTool.LIST_RELEASES,
    McpTool.GET_RELEASE,
    McpTool.CREATE_RELEASE,
    McpTool.UPDATE_RELEASE,
    McpTool.SWEEP_RELEASE,
    McpTool.SET_ITEM_RELEASE,
    McpTool.LIST_USERS,
    McpTool.LIST_SERVICE_ACCOUNTS,
    McpTool.CREATE_SERVICE_ACCOUNT,
)

_BUILTIN_NAMES = frozenset(tool.value for tool in CATALOG_ORDER)


def resolved_schema(
    spec: McpToolSpec,
    custom_field_properties: Mapping[str, Any],
    link_types: Sequence[str],
) -> dict[str, Any]:
    """THE input schema of a tool: a spec with an `input_schema_builder` gets
    the live projections, everything else its static schema. tools/list renders
    this and tools/call validates against it (RADD-1106) — one function, so the
    two cannot disagree."""
    if spec.input_schema_builder is not None:
        return spec.input_schema_builder(
            custom_field_properties=custom_field_properties, link_types=link_types
        )
    return dict(spec.input_schema)


def _entry(
    spec: McpToolSpec,
    custom_field_properties: Mapping[str, Any],
    link_types: Sequence[str],
) -> dict[str, Any]:
    """One tools/list entry."""
    return {
        "name": spec.name,
        "description": spec.description,
        "inputSchema": resolved_schema(spec, custom_field_properties, link_types),
    }


def build_catalog(
    custom_field_properties: Mapping[str, Any],
    *,
    link_types: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """The builtin half of tools/list, in CATALOG_ORDER. Pure; `link_types` are the
    instance's real keys (RADD-739), so an agent never guesses a user-defined name."""
    catalog: list[dict[str, Any]] = []
    for tool in CATALOG_ORDER:
        spec = registries.mcp_tools.get(tool.value)
        if spec is None:  # owner module absent/disabled — its tools go with it
            continue
        catalog.append(_entry(spec, custom_field_properties, link_types))
    return catalog


def registry_catalog(builtin_names: frozenset[str]) -> list[dict[str, Any]]:
    """Plugin-contributed tools (RADD-640), read live so a disabled plugin's vanish with it.
    A name the builtin section already lists is skipped, or it would be advertised twice."""
    return [
        _entry(spec, {}, ())
        for spec in registries.mcp_tools.values()
        if spec.name not in builtin_names
    ]


async def live_projections(session: AsyncSession) -> tuple[Mapping[str, Any], list[str]]:
    """The two live schema projections: the field registry's OpenAPI properties
    (refreshed — the same source OpenAPI reads) and the instance's link-type
    keys minus the auto-managed ones."""
    from radd.modules.linktypes import service as linktypes_service

    fields_openapi.refresh(await fields_service.list_fields(session))
    link_types = [
        definition.key
        for definition in await linktypes_service.list_types(session)
        if not definition.auto_managed
    ]
    return fields_openapi.schema_cache.properties, link_types


async def live_schema(session: AsyncSession, spec: McpToolSpec) -> dict[str, Any]:
    """The schema tools/list advertises for `spec` right now. A static schema
    needs no session (the stub-session tests dispatch such tools with none)."""
    if spec.input_schema_builder is None:
        return resolved_schema(spec, {}, ())
    custom_field_properties, link_types = await live_projections(session)
    return resolved_schema(spec, custom_field_properties, link_types)


async def catalog_fingerprint(session: AsyncSession, user: Any) -> str:
    """A short digest of the catalog THIS principal can see (RADD-740). Computed from the
    finished, filtered catalog, so a deploy, a plugin (un)mounting and the caller's own scopes
    all move it — no counter every mutation site must remember to bump."""
    catalog = await live_catalog(session, user)
    canonical = json.dumps(catalog, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


async def live_catalog(session: AsyncSession, user: Any = None) -> list[dict[str, Any]]:
    """build_catalog from the live projections plus plugin tools (RADD-640), NARROWED to
    what this principal may execute (spec 114). `user=None` returns the whole surface
    (an unauthenticated MCP request never reaches here — the router 401s first)."""
    custom_field_properties, link_types = await live_projections(session)
    catalog = build_catalog(custom_field_properties, link_types=link_types)
    catalog += registry_catalog(_BUILTIN_NAMES | frozenset(tool["name"] for tool in catalog))
    if user is None:
        return catalog
    from .requirements import visible_catalog  # deferred: requirements imports auth

    return await visible_catalog(session, user, catalog)
