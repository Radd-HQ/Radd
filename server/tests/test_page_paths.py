"""Pages are keyed by id and addressed by path (RADD-1233).

The rules the address bar, the tree and every emitted link stand on:

- a slug is unique among LIVE SIBLINGS and nowhere else — two pages may share
  a name under different parents, and an archived page no longer holds its;
- a path resolves in one query by walking the tree; a stale path resolves
  EXACTLY through the addresses the page used to have — the migration seeded
  those with every nested page's pre-1233 single-slug address, so there is no
  guessing step;
- a page's number is a permalink that a rename or move cannot break.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import NotFoundError
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.pages import core, paths, service as pages_service, spaces
from radd.modules.pages.models import PagePathHistory
from radd.modules.pages.schemas import PageCreate, PageSpaceCreate, PageUpdate

A, B, C, D = (uuid.uuid4() for _ in range(4))


class Row:
    def __init__(self, id, parent_id, slug):
        self.id, self.parent_id, self.slug = id, parent_id, slug


# --- pure ---------------------------------------------------------------------


def test_paths_fold_over_the_rows():
    rows = [Row(A, None, "a"), Row(B, A, "b"), Row(C, B, "c"), Row(D, None, "d")]
    assert core.page_paths(rows) == {A: "a", B: "a/b", C: "a/b/c", D: "d"}


def test_a_loop_in_the_data_yields_an_address_not_a_hang():
    assert core.page_paths([Row(A, B, "a"), Row(B, A, "b")]) == {A: "a", B: "b"}


def test_the_walk_matches_level_by_level():
    # Two pages slugged "b": one under a (the answer), one at the root (noise).
    rows = [Row(A, None, "a"), Row(B, A, "b"), Row(C, None, "b")]
    assert core.walk_path(rows, ["a", "b"]) == B
    assert core.walk_path(rows, ["b"]) == C
    assert core.walk_path(rows, ["a", "x"]) is None
    assert core.walk_path(rows, []) is None


# --- against the database -----------------------------------------------------


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
        email=f"pp-{uuid.uuid4().hex[:8]}@example.com",
        name="Admin",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(admin)
    await db.flush()
    return admin


async def _space(db, actor):
    return await spaces.create_space(
        db, PageSpaceCreate(name="Paths", slug=f"paths-{uuid.uuid4().hex[:6]}"), actor.id
    )


async def _page(db, space, actor, title, parent=None):
    return await pages_service.create_page(
        db, PageCreate(space_id=space.id, title=title, body="x", parent_id=parent), actor.id
    )


async def test_slugs_are_unique_among_live_siblings_only(db):
    admin = await _admin(db)
    space = await _space(db, admin)
    eng = await _page(db, space, admin, "Engineering")
    ops = await _page(db, space, admin, "Operations")
    a = await _page(db, space, admin, "Onboarding", eng.id)
    b = await _page(db, space, admin, "Onboarding", ops.id)
    assert a.slug == b.slug == "onboarding", "different parents: no suffix"
    c = await _page(db, space, admin, "Onboarding", eng.id)
    assert c.slug == "onboarding-2", "same parent: the suffix"

    await pages_service.archive_page(db, a.id, admin.id)
    d = await _page(db, space, admin, "Onboarding", eng.id)
    assert d.slug == "onboarding", "an archived sibling no longer holds the name"

    # While archived it is still reachable by its path when no live page holds
    # it, and yields to the live namesake when one does.
    assert (await paths.resolve(db, space, "engineering/onboarding")).id == d.id
    await pages_service.archive_page(db, d.id, admin.id)
    assert (await paths.resolve(db, space, "engineering/onboarding")).id in {a.id, d.id}
    await pages_service.unarchive_page(db, d.id, admin.id)

    # The archived page comes back beside the live one that took its name.
    await pages_service.unarchive_page(db, a.id, admin.id)
    await db.refresh(a)
    assert a.slug == "onboarding-3"
    assert (await pages_service.page_read(db, a)).path == "engineering/onboarding-3"


async def test_a_path_resolves_by_walking_and_a_number_is_a_permalink(db):
    admin = await _admin(db)
    space = await _space(db, admin)
    eng = await _page(db, space, admin, "Engineering")
    ops = await _page(db, space, admin, "Operations")
    under_eng = await _page(db, space, admin, "Runbook", eng.id)
    under_ops = await _page(db, space, admin, "Runbook", ops.id)

    assert (await paths.resolve(db, space, "engineering/runbook")).id == under_eng.id
    assert (await paths.resolve(db, space, "operations/runbook/")).id == under_ops.id
    with pytest.raises(NotFoundError):
        await paths.resolve(db, space, "engineering/nope")
    # A bare segment that is nobody's address is not guessed at.
    with pytest.raises(NotFoundError):
        await paths.resolve(db, space, "runbook")

    assert (await paths.resolve(db, space, str(under_eng.number))).id == under_eng.id
    assert (await paths.resolve(db, space, str(under_eng.id))).id == under_eng.id
    assert (await paths.by_key(db, str(under_ops.number))).id == under_ops.id
    read = await pages_service.page_read(db, under_ops)
    assert read.path == "operations/runbook" and read.number == under_ops.number
    assert [crumb.path for crumb in read.breadcrumb] == ["operations"]


async def test_a_stale_path_still_finds_the_page(db):
    admin = await _admin(db)
    space = await _space(db, admin)
    eng = await _page(db, space, admin, "Engineering")
    page = await _page(db, space, admin, "Laptops", eng.id)

    # A pre-1233 link to a nested page named only the page's slug. For pages
    # that existed at migration time the history row was SEEDED; a page made
    # after it has no such address, and the resolver does not guess.
    with pytest.raises(NotFoundError):
        await paths.resolve(db, space, "laptops")
    db.add(PagePathHistory(page_id=page.id, space_id=space.id, path="laptops"))
    await db.flush()
    assert (await paths.resolve(db, space, "laptops")).id == page.id

    # Rename: the old segment is remembered.
    await pages_service.update_page(db, page.id, PageUpdate(slug="hardware"), admin.id)
    assert (await paths.resolve(db, space, "engineering/hardware")).id == page.id
    assert (await paths.resolve(db, space, "engineering/laptops")).id == page.id

    # Move under a parent that already has a "hardware": the page yields and
    # is still found by the address it had a minute ago — EXACTLY, not by
    # guessing between it and the neighbour that holds the name now.
    ops = await _page(db, space, admin, "Operations")
    neighbour = await _page(db, space, admin, "Hardware", ops.id)
    await pages_service.update_page(db, page.id, PageUpdate(parent_id=ops.id), admin.id)
    await db.refresh(page)
    assert page.slug == "hardware-2"
    assert (await paths.resolve(db, space, "engineering/hardware")).id == page.id
    assert (await paths.resolve(db, space, "operations/hardware-2")).id == page.id
    assert (await paths.resolve(db, space, "operations/hardware")).id == neighbour.id

    # Renaming an ANCESTOR moves every address beneath it; all of them are kept.
    await pages_service.update_page(db, ops.id, PageUpdate(slug="ops"), admin.id)
    assert (await paths.resolve(db, space, "operations/hardware-2")).id == page.id
    assert (await paths.resolve(db, space, "ops/hardware-2")).id == page.id
