"""RADD-860 — placeholder slugs upgrade; established slugs stay promises.

Every UI-created page is born "Untitled" → slug `untitled-N`, and RADD-702's
rule (a title edit never moves the slug) preserved that placeholder forever.
Pinned here: the first REAL title upgrades a placeholder slug (collision
suffixed), an established slug never moves on a title edit, and the explicit
slug PATCH (the Change URL dialog's wire) still works with suffixing.

Rolled-back transactions on the compose DB.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.auth.models import User
from radd.modules.pages import service, spaces
from radd.modules.pages.schemas import PageCreate, PageSpaceCreate, PageUpdate


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def space(db):
    actor = (await db.execute(select(User.id))).scalars().first()
    row = await spaces.create_space(
        db,
        PageSpaceCreate(name=f"su-{uuid.uuid4().hex[:8]}", slug=f"su-{uuid.uuid4().hex[:8]}"),
        actor,
    )
    return row, actor


async def test_first_title_upgrades_the_placeholder(db, space):
    row, actor = space
    page = await service.create_page(db, PageCreate(space_id=row.id, title="Untitled"), actor)
    assert page.slug.startswith("untitled")
    renamed = await service.update_page(
        db, page.id, PageUpdate(title="Render Farm Runbook"), actor
    )
    assert renamed.slug == "render-farm-runbook"


async def test_established_slugs_never_move_on_title_edits(db, space):
    row, actor = space
    page = await service.create_page(
        db, PageCreate(space_id=row.id, title="Original", slug="original"), actor
    )
    renamed = await service.update_page(db, page.id, PageUpdate(title="Renamed Twice"), actor)
    assert renamed.slug == "original"  # RADD-702: the URL is a promise


async def test_same_title_under_two_parents_keeps_both_slugs(db, space):
    """RADD-1233 retired the per-space rule this test used to assert: a slug is
    unique among SIBLINGS, so two parents may each have a `setup`. The suffix
    still appears where it means something — beside a sibling."""
    row, actor = space
    a = await service.create_page(db, PageCreate(space_id=row.id, title="Parent A"), actor)
    b = await service.create_page(db, PageCreate(space_id=row.id, title="Parent B"), actor)
    first = await service.create_page(
        db, PageCreate(space_id=row.id, title="Untitled", parent_id=a.id), actor
    )
    second = await service.create_page(
        db, PageCreate(space_id=row.id, title="Untitled", parent_id=b.id), actor
    )
    third = await service.create_page(
        db, PageCreate(space_id=row.id, title="Untitled", parent_id=a.id), actor
    )
    one = await service.update_page(db, first.id, PageUpdate(title="Setup"), actor)
    two = await service.update_page(db, second.id, PageUpdate(title="Setup"), actor)
    three = await service.update_page(db, third.id, PageUpdate(title="Setup"), actor)
    assert one.slug == "setup"
    assert two.slug == "setup"  # a different parent: no suffix
    assert three.slug == "setup-2"  # the same parent: suffixed, never stuck at untitled


async def test_explicit_slug_change_still_works(db, space):
    row, actor = space
    page = await service.create_page(
        db, PageCreate(space_id=row.id, title="Keeper", slug="keeper"), actor
    )
    moved = await service.update_page(db, page.id, PageUpdate(slug="better-name"), actor)
    assert moved.slug == "better-name"
