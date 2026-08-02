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
from radd.modules.auth.types import InstanceRole, Permission
from radd.modules.mcp import tools
from radd.modules.mcp.catalog import build_catalog
from radd.modules.mcp.requirements import REQUIREMENTS, visible_catalog
from radd.modules.mcp.types import McpTool
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate

WRITE_TOOLS = {
    McpTool.CREATE_ITEM.value,
    McpTool.UPDATE_ITEM.value,
    McpTool.COMMENT_ITEM.value,
    McpTool.TRANSITION_ITEM.value,
    McpTool.LOG_WORK.value,
    McpTool.CREATE_RELEASE.value,
    McpTool.SET_ITEM_RELEASE.value,
    McpTool.CREATE_SERVICE_ACCOUNT.value,
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
    catalog = build_catalog({}, include_docs=True)
    return {tool["name"] for tool in await visible_catalog(db, user, catalog)}


# --- the catalog narrows ---


async def test_every_tool_declares_what_it_needs():
    """A tool nobody annotated stays visible by design; this test is what keeps
    that fallback from quietly becoming the norm."""
    catalog = build_catalog({}, include_docs=True)
    assert {tool["name"] for tool in catalog} <= set(REQUIREMENTS)


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
        {"global": ["doc.read"], "projects": {str(project.id): ["item.read"]}}
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

    catalog = await visible_catalog(db, admin, build_catalog({}, include_docs=True))
    create = next(t for t in catalog if t["name"] == McpTool.CREATE_ITEM.value)
    enum = create["inputSchema"]["properties"]["project_key"]["enum"]
    assert enum == [project.key]
    assert other.key not in enum


async def test_enum_degrades_to_a_string_above_the_threshold(db, project, monkeypatch):
    admin = await _user(db, InstanceRole.ADMIN)
    monkeypatch.setattr(settings, "mcp_project_enum_max", 0)

    catalog = await visible_catalog(db, admin, build_catalog({}, include_docs=True))
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


async def test_an_anonymous_principal_sees_nothing(db):
    assert await visible_catalog(db, None, build_catalog({}, include_docs=True)) == []


async def test_unscoped_admin_keeps_the_whole_catalog(db, project):
    """Spec 45's behaviour for every key that existed before this spec."""
    admin = await _user(db, InstanceRole.ADMIN)
    assert admin.token_scope is None
    full = {tool["name"] for tool in build_catalog({}, include_docs=True)}
    assert await _names(db, admin) == full
