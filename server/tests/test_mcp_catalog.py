"""Spec 114: tools/list is a function of the caller.

Two claims worth pinning. First, the catalog narrows — a viewer's key offers no
writes, an admin's offers the admin family, and the project parameter enumerates
exactly the projects the key may act in. Second, and more important: narrowing is
PRESENTATION. A tool hidden from the catalog and called anyway is refused by the
same permission check it always was, so a bug in the filter can cost context but
never authority.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import ForbiddenError
from radd.modules.auth import scopes
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.kernel import registries
from radd.kernel.mcptools import validate_arguments
from radd.modules.mcp import tools
from radd.modules.mcp.catalog import CATALOG_ORDER, build_catalog, live_schema
from radd.modules.mcp.protocol import JsonRpcError, JsonRpcRequest
from radd.modules.mcp.requirements import requirement_for, visible_catalog
from radd.modules.mcp.router import handle_request
from radd.modules.mcp.types import JsonRpcErrorCode, McpMethod, McpTool
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate

WRITE_TOOLS = {
    McpTool.CREATE_ITEM.value,
    McpTool.UPDATE_ITEM.value,
    McpTool.COMMENT_ITEM.value,
    McpTool.TRANSITION_ITEM.value,
    McpTool.LOG_WORK.value,
    McpTool.CREATE_RELEASE.value,
    McpTool.UPDATE_RELEASE.value,
    McpTool.SET_ITEM_RELEASE.value,
    McpTool.CREATE_SERVICE_ACCOUNT.value,
    McpTool.CREATE_PAGE.value,  # RADD-1005: the wiki, writable
    McpTool.UPDATE_PAGE.value,
    McpTool.MOVE_PAGE.value,
}
ADMIN_TOOLS = {
    McpTool.LIST_USERS.value,
    McpTool.LIST_SERVICE_ACCOUNTS.value,
    McpTool.CREATE_SERVICE_ACCOUNT.value,
}


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def project(db):
    return await projects_service.create_project(
        db, ProjectCreate(key=f"MC{uuid.uuid4().hex[:4].upper()}", name="MCP catalog")
    )


async def _user(db, role: InstanceRole) -> User:
    user = User(
        email=f"mcp-{uuid.uuid4().hex[:8]}@example.com", name="MCP", instance_role=role.value
    )
    db.add(user)
    await db.flush()
    return user


async def _names(db, user) -> set[str]:
    catalog = build_catalog({}, include_pages=True)
    return {tool["name"] for tool in await visible_catalog(db, user, catalog)}


# --- the catalog narrows ---


async def test_every_tool_declares_what_it_needs():
    """Every tool carries its requirement ON its kernel spec (RADD-640/889 — the
    builtin REQUIREMENTS table is gone), and anything unregistered is hidden as
    a wiring bug."""
    catalog = build_catalog({}, include_pages=True)
    assert all(requirement_for(tool["name"]) is not None for tool in catalog)


async def test_admin_sees_the_admin_family(db, project):
    admin = await _user(db, InstanceRole.ADMIN)
    names = await _names(db, admin)
    assert ADMIN_TOOLS <= names
    assert WRITE_TOOLS <= names


async def test_a_read_only_key_offers_no_writes(db, project):
    """The viewer case, expressed the way it actually arrives: an admin account
    holding a key scoped to reads."""
    admin = await _user(db, InstanceRole.ADMIN)
    admin.token_scope = scopes.parse_scope(
        {"global": ["page.read"], "projects": {str(project.id): ["item.read"]}}
    )
    names = await _names(db, admin)

    assert McpTool.SEARCH_ITEMS.value in names
    assert McpTool.GET_ITEM.value in names
    assert not (WRITE_TOOLS & names), sorted(WRITE_TOOLS & names)
    assert not (ADMIN_TOOLS & names)


async def test_a_member_sits_between(db, project):
    """The member floor is READ everywhere; writing takes a grant on the project.
    So an ungranted member's catalog is reads — which is the filter telling the
    truth, not withholding."""
    member = await _user(db, InstanceRole.MEMBER)
    names = await _names(db, member)

    assert McpTool.GET_ITEM.value in names
    assert McpTool.SEARCH_ITEMS.value in names
    assert McpTool.CREATE_ITEM.value not in names  # no grant on any project yet
    assert not (ADMIN_TOOLS & names)


# --- project enums ---


async def test_project_parameter_enumerates_only_permitted_projects(db, project):
    admin = await _user(db, InstanceRole.ADMIN)
    other = await projects_service.create_project(
        db, ProjectCreate(key=f"MD{uuid.uuid4().hex[:4].upper()}", name="Other")
    )
    admin.token_scope = scopes.parse_scope(
        {"projects": {str(project.id): ["item.read", "item.create"]}}
    )

    catalog = await visible_catalog(db, admin, build_catalog({}, include_pages=True))
    create = next(t for t in catalog if t["name"] == McpTool.CREATE_ITEM.value)
    enum = create["inputSchema"]["properties"]["project_key"]["enum"]
    assert enum == [project.key]
    assert other.key not in enum


async def test_enum_degrades_to_a_string_above_the_threshold(db, project, monkeypatch):
    admin = await _user(db, InstanceRole.ADMIN)
    monkeypatch.setattr(settings, "mcp_project_enum_max", 0)

    catalog = await visible_catalog(db, admin, build_catalog({}, include_pages=True))
    create = next(t for t in catalog if t["name"] == McpTool.CREATE_ITEM.value)
    prop = create["inputSchema"]["properties"]["project_key"]
    assert "enum" not in prop
    assert "available to this key" in prop["description"]
    assert prop["type"] == "string"  # still callable, just unconstrained


# --- hiding is not the enforcement ---


async def test_a_hidden_tool_is_still_refused_when_called(db, project):
    """The claim that makes the whole design safe."""
    admin = await _user(db, InstanceRole.ADMIN)
    admin.token_scope = scopes.parse_scope({"projects": {str(project.id): ["item.read"]}})

    assert McpTool.CREATE_SERVICE_ACCOUNT.value not in await _names(db, admin)
    with pytest.raises(ForbiddenError):
        await tools.call_tool(db, admin, McpTool.CREATE_SERVICE_ACCOUNT.value, {"name": "sneaky"})


# --- cross-project reads admit scoped keys (RADD-672) ---


async def test_a_scoped_key_lists_exactly_its_projects(db, project):
    """list_projects/search_items were LISTED for a project-scoped key while the
    handlers demanded the GLOBAL item.read — a catalog/enforcement disagreement
    in exactly the direction spec 114 promises cannot happen. The gate is now
    item.read ANYWHERE, and the answer is scoped to where it holds."""
    admin = await _user(db, InstanceRole.ADMIN)
    await projects_service.create_project(
        db, ProjectCreate(key=f"ME{uuid.uuid4().hex[:4].upper()}", name="Elsewhere")
    )
    admin.token_scope = scopes.parse_scope({"projects": {str(project.id): ["item.read"]}})

    listed = await tools.call_tool(db, admin, McpTool.LIST_PROJECTS.value, {})
    assert [p["key"] for p in listed["projects"]] == [project.key]


async def test_a_scoped_key_searches_without_the_global_atom(db, project):
    admin = await _user(db, InstanceRole.ADMIN)
    admin.token_scope = scopes.parse_scope({"projects": {str(project.id): ["item.read"]}})

    result = await tools.call_tool(
        db, admin, McpTool.SEARCH_ITEMS.value, {"slq": f"project = {project.key}"}
    )
    assert result["count"] == 0  # the fixture project is empty; the refusal was the bug


async def test_item_read_nowhere_is_still_refused(db, project):
    """require_anywhere is a gate, not a bypass: a key with no item.read at all
    stays refused."""
    admin = await _user(db, InstanceRole.ADMIN)
    admin.token_scope = scopes.parse_scope({"projects": {str(project.id): ["comment.write"]}})

    with pytest.raises(ForbiddenError):
        await tools.call_tool(db, admin, McpTool.LIST_PROJECTS.value, {})


async def test_an_anonymous_principal_sees_nothing(db):
    assert await visible_catalog(db, None, build_catalog({}, include_pages=True)) == []


async def test_unscoped_admin_keeps_the_whole_catalog(db, project):
    """Spec 45's behaviour for every key that existed before this spec."""
    admin = await _user(db, InstanceRole.ADMIN)
    assert admin.token_scope is None
    full = {tool["name"] for tool in build_catalog({}, include_pages=True)}
    assert await _names(db, admin) == full


# --- the tracking workflow end to end (RADD-673: names in, ids resolved) ---


async def test_the_tracking_workflow_runs_entirely_over_mcp(db, project):
    """File an epic + child with type/points, log categorized time, create a
    released version, sweep the child into it — zero REST, zero raw ids. This is
    the CLAUDE.md loop, which is why these parameters exist."""
    from radd.modules.itemtypes import service as itemtypes_service
    from radd.modules.timelogging import categories as timelogging_categories, enablement
    from radd.modules.timelogging.schemas import WorkCategoryCreate

    admin = await _user(db, InstanceRole.ADMIN)
    await enablement.set_enabled(db, project.id, True)  # timelogging is per-project-optional
    types = {t.name for t in await itemtypes_service.list_types(db, project.id)}
    assert {"Epic", "Bug"} <= types  # seeded defaults; the names the tool resolves
    if not any(
        c.name == "Development" for c in await timelogging_categories.list_categories(db)
    ):
        await timelogging_categories.create_category(db, WorkCategoryCreate(name="Development"))

    epic = await tools.call_tool(
        db,
        admin,
        McpTool.CREATE_ITEM.value,
        {"project_key": project.key, "title": "The wave", "kind": "epic", "type": "Epic"},
    )
    child = await tools.call_tool(
        db,
        admin,
        McpTool.CREATE_ITEM.value,
        {
            "project_key": project.key,
            "title": "One unit of it",
            "type": "Bug",
            "parent": epic["key"],
            "estimate_points": 3,
            "start_date": "2026-09-01",
        },
    )
    # RADD-861: writes answer with a compact receipt — the write's EFFECT is
    # asserted through the read tool, which is what an agent that cared would do.
    assert set(child) >= {"key", "id", "state"}
    fetched = await tools.call_tool(db, admin, McpTool.GET_ITEM.value, {"key": child["key"]})
    assert fetched["item"]["parent"]["key"] == epic["key"]
    assert fetched["item"]["type"]["name"] == "Bug"
    assert fetched["item"]["estimate_points"] == 3.0
    assert fetched["item"]["start_date"] == "2026-09-01"

    # Plain dates ride the same present-and-null rule as the other clearables.
    await tools.call_tool(
        db,
        admin,
        McpTool.UPDATE_ITEM.value,
        {"key": child["key"], "start_date": None, "target_date": "2026-09-30"},
    )
    fetched = await tools.call_tool(db, admin, McpTool.GET_ITEM.value, {"key": child["key"]})
    assert fetched["item"]["start_date"] is None
    assert fetched["item"]["target_date"] == "2026-09-30"

    logged = await tools.call_tool(
        db,
        admin,
        McpTool.LOG_WORK.value,
        {"key": child["key"], "time_spent": "45m", "category": "Development"},
    )
    assert logged["time_spent"] == "45m"  # receipt; the category resolution is
    # covered by the worklog listing the timesheet reads

    release = await tools.call_tool(
        db,
        admin,
        McpTool.CREATE_RELEASE.value,
        {"project_key": project.key, "version": "9.9.9", "status": "released"},
    )
    assert release["status"] == "released"

    # The pipeline's own invariants live in test_release_pipeline.py; here the
    # claim is the TOOL: resolve by version, same atom as the REST sweep, and a
    # project with no waiting state configured sweeps nothing rather than erroring.
    swept = await tools.call_tool(
        db,
        admin,
        McpTool.SWEEP_RELEASE.value,
        {"project_key": project.key, "version": "9.9.9"},
    )
    assert swept == {"release": "9.9.9", "items_shipped": 0}


# --- RADD-1106: every tool refuses arguments its advertised schema rejects ---


@pytest.mark.parametrize("tool", [tool.value for tool in CATALOG_ORDER])
async def test_every_tool_validates_against_the_schema_it_advertises(db, tool):
    """Against the LIVE schema (custom fields, link types) — the same object
    tools/list renders. A tool with required properties refuses `{}` with a
    -32602 that names what is missing; a tool without any accepts `{}` at the
    validation layer, so the check is never vacuous."""
    admin = await _user(db, InstanceRole.ADMIN)
    spec = registries.mcp_tools[tool]
    schema = await live_schema(db, spec)
    required = schema.get("required", [])
    if not required:
        validate_arguments(tool, schema, {})
        return
    with pytest.raises(JsonRpcError) as info:
        await handle_request(
            db,
            admin,
            JsonRpcRequest(
                method=McpMethod.TOOLS_CALL, params={"name": tool, "arguments": {}}, id=1
            ),
        )
    assert info.value.code is JsonRpcErrorCode.INVALID_PARAMS
    for name in required:
        assert f"'{name}'" in str(info.value)


# --- RADD-1005: the wiki is writable over MCP ---


async def test_the_wiki_is_writable_over_mcp(db):
    """Create in a space by slug, edit (a new version), move under a parent —
    and a key without page.write neither sees the write tools nor runs one."""
    from radd.modules.pages import spaces
    from radd.modules.pages.schemas import PageSpaceCreate

    admin = await _user(db, InstanceRole.ADMIN)
    slug = f"mcp-{uuid.uuid4().hex[:8]}"
    space = await spaces.create_space(db, PageSpaceCreate(name="MCP wiki", slug=slug), admin.id)

    created = await tools.call_tool(
        db, admin, McpTool.CREATE_PAGE.value, {"space": slug, "title": "Runbook", "body": "v1"}
    )
    assert created["version"] == 1 and created["parent_id"] is None
    assert "body" not in created  # RADD-861: a receipt, not an echo

    edited = await tools.call_tool(
        db,
        admin,
        McpTool.UPDATE_PAGE.value,
        {"id": created["id"], "body": "v2", "expected_version": 1},
    )
    assert edited["version"] == 2
    fetched = await tools.call_tool(db, admin, McpTool.GET_PAGE.value, {"id": created["id"]})
    assert fetched["body"] == "v2"

    parent = await tools.call_tool(
        db, admin, McpTool.CREATE_PAGE.value, {"space": str(space.id), "title": "Parent"}
    )
    moved = await tools.call_tool(
        db, admin, McpTool.MOVE_PAGE.value, {"id": created["id"], "parent_id": parent["id"]}
    )
    assert moved["parent_id"] == parent["id"]

    reader = await _user(db, InstanceRole.ADMIN)
    reader.token_scope = scopes.parse_scope({"global": ["page.read"]})
    page_writes = {McpTool.CREATE_PAGE.value, McpTool.UPDATE_PAGE.value, McpTool.MOVE_PAGE.value}
    assert not (page_writes & await _names(db, reader))
    with pytest.raises(ForbiddenError):
        await tools.call_tool(
            db, reader, McpTool.CREATE_PAGE.value, {"space": slug, "title": "Sneaky"}
        )
    with pytest.raises(ForbiddenError):
        await tools.call_tool(
            db, reader, McpTool.UPDATE_PAGE.value, {"id": created["id"], "body": "sneaky"}
        )


# --- plugin-contributed tools ride the kernel registry (RADD-640) ---


@pytest.fixture
def registry_tool():
    """A minimal plugin tool registered directly (the loader does exactly this
    when a plugin manifest carries mcp_tools). Cleaned up so no other test sees
    the catalog grow."""
    from radd.kernel import registries
    from radd.kernel.specs import McpToolSpec

    async def handler(session, actor, args):
        return {"echo": args.get("project_key"), "ran": True}

    spec = McpToolSpec(
        name="fake_plugin_tool",
        description="test tool",
        input_schema={
            "type": "object",
            "properties": {"project_key": {"type": "string"}},
            "required": ["project_key"],
            "additionalProperties": False,
        },
        handler=handler,
        permission="item.create",
        project_scoped=True,
        project_param="project_key",
    )
    registries.mcp_tools[spec.name] = spec
    yield spec
    registries.mcp_tools.pop(spec.name, None)


async def test_a_registered_tool_is_filtered_like_a_builtin(db, project, registry_tool):
    """The spec IS the annotation: visible with the atom (project enum rewritten),
    hidden without — no REQUIREMENTS entry, no plugin-side filter code."""
    from radd.modules.mcp.catalog import registry_catalog

    extra = registry_catalog(frozenset())
    catalog = build_catalog({}, include_pages=True) + extra

    admin = await _user(db, InstanceRole.ADMIN)
    admin.token_scope = scopes.parse_scope(
        {"projects": {str(project.id): ["item.read", "item.create"]}}
    )
    visible = await visible_catalog(db, admin, catalog)
    tool = next(t for t in visible if t["name"] == registry_tool.name)
    assert tool["inputSchema"]["properties"]["project_key"]["enum"] == [project.key]

    reader = await _user(db, InstanceRole.ADMIN)
    reader.token_scope = scopes.parse_scope({"projects": {str(project.id): ["item.read"]}})
    assert registry_tool.name not in {t["name"] for t in await visible_catalog(db, reader, catalog)}


async def test_a_registered_tool_is_enforced_before_its_handler_runs(db, project, registry_tool):
    """The kernel requires the declared atom — the handler holds no authz call, and
    a key without the atom is refused before it runs."""
    reader = await _user(db, InstanceRole.ADMIN)
    reader.token_scope = scopes.parse_scope({"projects": {str(project.id): ["item.read"]}})
    with pytest.raises(ForbiddenError):
        await tools.call_tool(db, reader, registry_tool.name, {"project_key": project.key})

    writer = await _user(db, InstanceRole.ADMIN)
    writer.token_scope = scopes.parse_scope(
        {"projects": {str(project.id): ["item.read", "item.create"]}}
    )
    result = await tools.call_tool(db, writer, registry_tool.name, {"project_key": project.key})
    assert result == {"echo": project.key, "ran": True}


async def test_an_unregistered_tool_stops_dispatching(db, project, registry_tool):
    """The spec-94 unmount promise for MCP: leaving the registry removes the tool
    from catalog AND dispatch in the same breath."""
    from radd.kernel import registries
    from radd.modules.mcp.catalog import registry_catalog

    registries.mcp_tools.pop(registry_tool.name)
    assert registry_tool.name not in {t["name"] for t in registry_catalog(frozenset())}
    admin = await _user(db, InstanceRole.ADMIN)
    with pytest.raises(tools.UnknownToolError):
        await tools.call_tool(db, admin, registry_tool.name, {"project_key": project.key})


async def test_a_colliding_name_cannot_shadow_a_builtin(registry_tool):
    """A plugin tool named like a builtin is skipped from the catalog: dispatch
    resolves builtins first, so listing it would advertise a tool that never runs."""
    from radd.modules.mcp.catalog import registry_catalog

    assert registry_tool.name in {t["name"] for t in registry_catalog(frozenset())}
    assert registry_tool.name not in {
        t["name"] for t in registry_catalog(frozenset({registry_tool.name}))
    }


# --- RADD-740: the fingerprint the change-stream watches -----------------------


async def test_the_fingerprint_differs_between_principals(db):
    """It has to be per-CALLER, not per-deploy. Spec 114 makes the catalog a
    function of the key, so a global digest would tell a scoped agent nothing
    changed when its own scopes were widened."""
    from radd.modules.mcp.catalog import catalog_fingerprint

    admin = await _user(db, InstanceRole.ADMIN)
    member = await _user(db, InstanceRole.MEMBER)
    assert await catalog_fingerprint(db, admin) != await catalog_fingerprint(db, member)


async def test_the_fingerprint_is_stable_when_nothing_changed(db):
    from radd.modules.mcp.catalog import catalog_fingerprint

    admin = await _user(db, InstanceRole.ADMIN)
    assert await catalog_fingerprint(db, admin) == await catalog_fingerprint(db, admin)


async def test_mounting_a_plugin_tool_moves_the_fingerprint(db):
    """The reason the stream polls a digest rather than subscribing to events:
    a plugin mounting is not an event this process would otherwise notice."""
    from radd.kernel.registry import registries
    from radd.kernel.specs import McpToolSpec
    from radd.modules.mcp.catalog import catalog_fingerprint

    admin = await _user(db, InstanceRole.ADMIN)
    before = await catalog_fingerprint(db, admin)

    async def _handler(session, actor, args):
        return {}

    registries.mcp_tools["radd740_probe"] = McpToolSpec(
        name="radd740_probe", description="probe", input_schema={"type": "object"},
        handler=_handler,
    )
    try:
        assert await catalog_fingerprint(db, admin) != before
    finally:
        registries.mcp_tools.pop("radd740_probe", None)
    assert await catalog_fingerprint(db, admin) == before


async def test_the_change_stream_actually_serves(db):
    """RADD-740 shipped BROKEN because nothing here opened the stream.

    `_initialize_result()` does not touch `SSE_HEADERS`, and no test called the
    GET route, so a missing import passed every check I ran and then 500'd in
    production on the first connection. This pulls the first frame, which is the
    cheapest thing that exercises the response construction end to end.
    """
    import asyncio

    from radd.modules.mcp.router import mcp_stream

    admin = await _user(db, InstanceRole.ADMIN)
    response = await mcp_stream(admin, db)
    assert response.media_type == "text/event-stream"
    assert response.headers["cache-control"].startswith("no-cache")
    first = await asyncio.wait_for(response.body_iterator.__anext__(), timeout=5)
    assert first.startswith(":")  # the connect flush
    await response.body_iterator.aclose()
