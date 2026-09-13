"""The MCP tool catalog (spec 45) — tools/list payload generation.

Since RADD-889 the catalog is COMPOSED, not written: every tool is a kernel
`McpToolSpec` contributed by its OWNER module (items, timelogging, releases,
pages, projects, auth, search — plus any plugin), and this module only orders,
renders and filters them. `build_catalog` stays the pure seam it always was:
the live projections (custom-field properties from the field registry — the
SAME source as OpenAPI — and the spec-91 link-type keys) are passed IN and
handed to each spec's `input_schema_builder`, so studio-defined custom fields
appear as documented `custom_fields` properties automatically. The doc tools
ride the pages plugin's own registration — its absence removes them (the
spec-94 unmount path replaced the old pages_bridge feature probe).
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from radd.kernel.specs import McpToolSpec
from radd.modules.fields import openapi as fields_openapi, service as fields_service

from .types import PAGE_TOOLS, McpTool

#: The builtin catalog in its spec-45/114 wire order — the order agents have
#: always seen. The ENTRIES come from the kernel registry (each owner module's
#: manifest); this tuple carries only presentation order and the builtin/plugin
#: split (a name here is skipped by `registry_catalog`). A tool whose owner is
#: absent or disabled simply drops out.
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
    McpTool.GET_PAGE,
    McpTool.SEARCH_PAGES,
    McpTool.CREATE_PAGE,
    McpTool.UPDATE_PAGE,
    McpTool.MOVE_PAGE,
    # --- spec 114 families. Each appears only for a key that may execute it; the
    # filter (requirements.visible_catalog) reads the same permission engine the
    # call itself does, so the catalog cannot drift from the enforcement.
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
    include_pages: bool,
    link_types: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """The builtin half of the tools/list payload. Pure: the registry projections
    are passed in.

    `link_types` (RADD-739) enumerates the instance's ACTUAL link-type keys.
    They are user-definable (spec 91), so a free-string parameter would have an
    agent guessing whether this instance says `blocks`, `depends_on`, or
    something a studio invented — the same argument spec 114 already makes for
    the project parameter.
    """
    from radd.kernel import registries  # deferred: the kernel must not be a hard import cycle

    catalog: list[dict[str, Any]] = []
    for tool in CATALOG_ORDER:
        if tool in PAGE_TOOLS and not include_pages:
            continue
        spec = registries.mcp_tools.get(tool.value)
        if spec is None:  # owner module absent/disabled — its tools go with it
            continue
        catalog.append(_entry(spec, custom_field_properties, link_types))
    return catalog


def pages_available() -> bool:
    """Whether the pages plugin has contributed the doc tools (RADD-889 — the
    registry IS the feature detection: a disabled plugin's specs are gone)."""
    from radd.kernel import registries

    return all(tool.value in registries.mcp_tools for tool in PAGE_TOOLS)


def registry_catalog(builtin_names: frozenset[str]) -> list[dict[str, Any]]:
    """Plugin-contributed tools (RADD-640), read live from the kernel registry so
    a disabled plugin's tools vanish with it. A name colliding with a builtin is
    skipped: the dispatcher would resolve identically either way, but the builtin
    section already lists it — a second entry would advertise the same tool twice."""
    from radd.kernel import registries  # deferred: the kernel must not be a hard import cycle

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
    """A short digest of the catalog THIS principal can see (RADD-740).

    Covers every reason the surface can move — a deploy adding a tool, a plugin
    mounting or unmounting, and the caller's own scopes changing — because it is
    computed from the finished, already-filtered catalog rather than from a
    counter that each mutation site would have to remember to bump.
    """
    catalog = await live_catalog(session, user)
    canonical = json.dumps(catalog, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


async def live_catalog(session: AsyncSession, user: Any = None) -> list[dict[str, Any]]:
    """build_catalog fed from the live registry (same projection as OpenAPI), plus
    plugin-contributed tools (RADD-640), then NARROWED to what this principal may
    execute (spec 114).

    `user=None` returns the whole catalog — the shape tests and the OpenAPI
    projection want the full surface, and an unauthenticated MCP request never
    reaches here (the router 401s first).
    """
    custom_field_properties, link_types = await live_projections(session)
    catalog = build_catalog(
        custom_field_properties, include_pages=pages_available(), link_types=link_types
    )
    catalog += registry_catalog(_BUILTIN_NAMES | frozenset(tool["name"] for tool in catalog))
    if user is None:
        return catalog
    from .requirements import visible_catalog  # deferred: requirements imports auth

    return await visible_catalog(session, user, catalog)
