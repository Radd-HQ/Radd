"""Cross-project hierarchy & links (spec 80): the same-PROJECT invariant on
parents and manual links is lifted — items link/parent freely across projects
(spec 86 removed the workspace boundary; there is only one global scope). The
kind ladder (epic ← issue ← subtask) is unchanged.

DB-backed (compose Postgres) — flushed, never committed; the session rolls back
at teardown, so rows never persist.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.exceptions import ConflictError
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.items import service as items
from radd.modules.items.enums import ItemKind, ItemLinkType
from radd.modules.items.schemas import ItemCreate, ItemLinkCreate, ItemUpdate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def actor(db) -> User:
    user = User(
        email=f"xproj-{uuid.uuid4().hex[:8]}@example.com",
        name="Cross Project Tester",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


async def _project(db, prefix: str):
    return await projects_service.create_project(
        db,
        ProjectCreate(
            key=f"{prefix}{uuid.uuid4().hex[:4].upper()}",
            name=prefix,
        ),
    )


async def test_cross_project_parent_accepted(db, actor):
    p1 = await _project(db, "PA")
    p2 = await _project(db, "PB")
    epic = await items.create_item(
        db, ItemCreate(project_id=p1.id, title="epic", kind=ItemKind.EPIC), actor
    )
    # Create path: an issue in P2 under an epic in P1.
    issue = await items.create_item(
        db, ItemCreate(project_id=p2.id, title="issue", parent_id=epic.id), actor
    )
    assert issue.parent is not None and issue.parent.id == epic.id

    # Update path: re-parenting an existing item across projects works too.
    orphan = await items.create_item(db, ItemCreate(project_id=p2.id, title="orphan"), actor)
    updated = await items.update_item(db, orphan.id, ItemUpdate(parent_id=epic.id), actor)
    assert updated.parent is not None and updated.parent.id == epic.id


async def test_kind_ladder_still_enforced_across_projects(db, actor):
    p1 = await _project(db, "LA")
    p2 = await _project(db, "LB")
    issue = await items.create_item(db, ItemCreate(project_id=p1.id, title="issue"), actor)
    # An issue's parent must be an EPIC — crossing projects doesn't relax the ladder.
    with pytest.raises(ConflictError, match="must be of kind"):
        await items.create_item(
            db, ItemCreate(project_id=p2.id, title="child", parent_id=issue.id), actor
        )


async def test_cross_project_link_accepted(db, actor):
    p1 = await _project(db, "KA")
    p2 = await _project(db, "KB")
    source = await items.create_item(db, ItemCreate(project_id=p1.id, title="source"), actor)
    target = await items.create_item(db, ItemCreate(project_id=p2.id, title="target"), actor)
    read = await items.add_item_link(
        db,
        source.id,
        ItemLinkCreate(target_id=target.id, link_type=ItemLinkType.BLOCKS),
        actor,
    )
    assert any(link.item.id == target.id for link in read.links.outgoing)


async def test_link_search_ranks_same_project_first(db, actor):
    p1 = await _project(db, "SA")
    p2 = await _project(db, "SB")
    marker = f"needle-{uuid.uuid4().hex[:6]}"
    # Created in the OTHER project first — ordering must come from the tier,
    # not from creation order or numbers.
    other = await items.create_item(
        db, ItemCreate(project_id=p2.id, title=f"{marker} other"), actor
    )
    mine = await items.create_item(
        db, ItemCreate(project_id=p1.id, title=f"{marker} mine"), actor
    )
    results = await items.link_search(db, project_id=p1.id, q=marker, actor=actor, limit=8)
    ids = [result.id for result in results]
    assert set(ids) == {mine.id, other.id}
    assert ids.index(mine.id) < ids.index(other.id)  # same-project tier first
    by_id = {result.id: result for result in results}
    assert by_id[other.id].key.startswith("SB")  # keys carry the item's OWN project
    assert by_id[mine.id].key.startswith("SA")
