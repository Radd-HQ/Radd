"""`audit_log` over MCP (spec 123, RADD-1172).

Three claims: the tool rides the kernel registry (catalog + dispatch, no code
in `mcp`); it is hidden from a key that manages no project and refused when
called anyway; and it answers the question the tracker's own workflow asks —
"who changed RADD-123 and from what to what" — through the same service the
REST route uses, so the two cannot disagree.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import ForbiddenError
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.items import service as items
from radd.modules.items.schemas import ItemCreate, ItemUpdate
from radd.modules.mcp import tools
from radd.modules.mcp.catalog import build_catalog, registry_catalog
from radd.modules.mcp.requirements import visible_catalog
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _user(db, role: InstanceRole) -> User:
    user = User(
        email=f"mcp-audit-{uuid.uuid4().hex[:8]}@example.com",
        name="MCP Auditor",
        instance_role=role.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _names(db, user):
    catalog = build_catalog({}, include_pages=True)
    catalog += registry_catalog(frozenset(tool["name"] for tool in catalog))
    return {tool["name"] for tool in await visible_catalog(db, user, catalog)}


async def test_tool_is_registered_and_gated(db):
    admin = await _user(db, InstanceRole.ADMIN)
    member = await _user(db, InstanceRole.MEMBER)
    # A project-scoped tool is offered where its atom holds — somewhere must exist.
    await projects_service.create_project(
        db, ProjectCreate(key=f"MG{uuid.uuid4().hex[:4].upper()}", name="Gate"), actor_id=admin.id
    )
    assert "audit_log" in await _names(db, admin)
    assert "audit_log" not in await _names(db, member)
    with pytest.raises(ForbiddenError):
        await tools.call_tool(db, member, "audit_log", {})


async def test_who_changed_the_issue(db):
    admin = await _user(db, InstanceRole.ADMIN)
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"MA{uuid.uuid4().hex[:4].upper()}", name="MCP audit"), actor_id=admin.id
    )
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="Before"), admin)
    await items.update_item(db, item.id, ItemUpdate(title="After"), admin)
    await db.flush()

    result = await tools.call_tool(
        db, admin, "audit_log", {"project_key": project.key, "entity_key": item.key, "changed_field": "title"}
    )
    assert result["count"] == 1
    entry = result["entries"][0]
    assert entry["actor"] == admin.name and entry["label"] == "Item updated"
    assert entry["entity"] == f"{item.key} After" and entry["project"] == project.key
    assert entry["changes"] == [{"field": "title", "from": "Before", "to": "After"}]

    by_person = await tools.call_tool(
        db, admin, "audit_log", {"project_key": project.key, "actor_email": admin.email, "q": "After"}
    )
    assert any(e["id"] == entry["id"] for e in by_person["entries"])
