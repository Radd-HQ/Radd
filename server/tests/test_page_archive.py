"""Archived pages are browsable and restorable (RADD-1228, GitHub #7).

Two contracts the archive browser stands on, at the service seam:

- the `include_archived` listing says WHICH rows are archived (`archived_at`),
  because a live page hidden under an archived ancestor is in that listing too
  and the browser must not offer to "restore" something that is not archived;
- restoring a page under an archived ancestor restores the chain, or the
  button would leave the page exactly as invisible as it found it.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.events.models import Event
from radd.modules.pages import service as pages_service, spaces
from radd.modules.pages.schemas import PageCreate, PageSpaceCreate
from radd.modules.pages.types import PageEvent


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _admin(db) -> User:
    admin = User(
        email=f"arc-{uuid.uuid4().hex[:8]}@example.com",
        name="Admin",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(admin)
    await db.flush()
    return admin


async def _tree(db, actor):
    """root > mid > leaf, plus an unrelated sibling of mid."""
    space = await spaces.create_space(
        db, PageSpaceCreate(name="Archive", slug=f"archive-{uuid.uuid4().hex[:6]}"), actor.id
    )

    async def page(title, parent=None):
        return await pages_service.create_page(
            db,
            PageCreate(space_id=space.id, title=title, body="x", parent_id=parent),
            actor.id,
        )

    root = await page("Root")
    mid = await page("Mid", root.id)
    leaf = await page("Leaf", mid.id)
    other = await page("Other", root.id)
    return space, root, mid, leaf, other


async def test_the_archived_listing_marks_exactly_the_archived_rows(db):
    admin = await _admin(db)
    space, root, mid, leaf, other = await _tree(db, admin)
    await pages_service.archive_page(db, mid.id, admin.id)

    live = {row.id: row for row in await pages_service.list_pages(db, space.id, actor=admin)}
    assert set(live) == {root.id, other.id}, "the archived subtree is pruned from the tree"
    assert all(row.archived_at is None for row in live.values())

    full = {
        row.id: row
        for row in await pages_service.list_pages(db, space.id, include_archived=True, actor=admin)
    }
    assert set(full) == {root.id, mid.id, leaf.id, other.id}
    assert full[mid.id].archived_at is not None
    # Hidden with its parent, but NOT archived in its own right.
    assert full[leaf.id].archived_at is None
    assert full[root.id].archived_at is None


async def test_restoring_a_page_under_an_archived_ancestor_restores_the_chain(db):
    admin = await _admin(db)
    space, root, mid, leaf, other = await _tree(db, admin)
    await pages_service.archive_page(db, leaf.id, admin.id)
    await pages_service.archive_page(db, mid.id, admin.id)
    await pages_service.archive_page(db, other.id, admin.id)

    await pages_service.unarchive_page(db, leaf.id, admin.id)

    live = {row.id for row in await pages_service.list_pages(db, space.id, actor=admin)}
    assert leaf.id in live, "the restored page is reachable again"
    assert mid.id in live, "its archived ancestor came back with it"
    # A page archived in its own right, off the chain, is untouched.
    assert other.id not in live

    ids = {str(page.id) for page in (leaf, mid, root, other)}
    restored = (
        await db.execute(
            select(Event.entity_id).where(
                Event.event_type == PageEvent.PAGE_RESTORED.value, Event.entity_id.in_(ids)
            )
        )
    ).scalars().all()
    assert set(restored) == {str(leaf.id), str(mid.id)}, "one restore event per page that changed"
