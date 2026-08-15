"""RADD-1087 — the MCP surface can move an item between projects.

The backend machinery is spec 68's bulk move (aliases, state/type mapping,
both-sides write checks); this pins the MCP wrapper end to end: real
projects, a real admin, the old key still resolving afterwards.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.items import mcptools
from radd.modules.items.service import create_item, find_item_by_key
from radd.modules.items.schemas import ItemCreate
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


async def test_move_item_over_mcp_keeps_identity_and_redirects(db):
    admin = User(
        email=f"mv-{uuid.uuid4().hex[:8]}@example.com",
        name="Mover",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(admin)
    await db.flush()
    suffix = uuid.uuid4().hex[:4].upper()
    source = await projects_service.create_project(
        db, ProjectCreate(key=f"MA{suffix}", name="Move A"), actor_id=admin.id
    )
    target = await projects_service.create_project(
        db, ProjectCreate(key=f"MB{suffix}", name="Move B"), actor_id=admin.id
    )
    created = await create_item(
        db, ItemCreate(project_id=source.id, title="crosses the border"), actor=admin
    )

    result = await mcptools._move_item(
        db, admin, {"key": created.key, "target_project_key": target.key}
    )
    assert result["moved"] is True
    assert result["old_key"] == created.key
    assert result["new_key"].startswith(f"MB{suffix}-")

    # identity survives; the old key still resolves via its alias
    moved = await find_item_by_key(db, result["new_key"])
    assert moved is not None and moved.id == created.id
    aliased = await find_item_by_key(db, created.key)
    assert aliased is not None and aliased.id == created.id
