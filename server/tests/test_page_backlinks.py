"""Backlinks (RADD-713).

The parser is the part worth testing: it decides what counts as a page linking
to another page, and getting it wrong is invisible — a missing backlink looks
like "nobody linked here" and a spurious one looks like someone did.

The rest (index maintained on save, removal on unlink) is exercised through the
service against a real session, because the invariant is about the WRITE PATH
keeping the index true, not about a function returning a set.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.auth.models import User
from radd.modules.pages import backlinks, service, spaces
from radd.modules.pages.models import PageLink
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
async def wiki(db):
    """A space with two pages: `source` and `target`."""
    actor = (await db.execute(select(User.id))).scalars().first()
    space = await spaces.create_space(
        db, PageSpaceCreate(name=f"bl-{uuid.uuid4().hex[:8]}", slug=f"bl-{uuid.uuid4().hex[:8]}"), actor
    )
    target = await service.create_page(
        db, PageCreate(space_id=space.id, title="Target", slug="target"), actor
    )
    source = await service.create_page(
        db, PageCreate(space_id=space.id, title="Source", slug="source", body="seed"), actor
    )
    return space, source, target, actor


async def _sources_of(db, page_id) -> list[uuid.UUID]:
    rows = await db.execute(select(PageLink.source_page_id).where(PageLink.target_page_id == page_id))
    return list(rows.scalars())


# --- the parser ---------------------------------------------------------------


@pytest.mark.parametrize(
    "body, expected",
    [
        ("[a](/pages/eng/runbook)", {("eng", "runbook")}),
        ("[a](https://project.radd-hq.com/pages/eng/runbook)", {("eng", "runbook")}),
        ('<a href="/pages/eng/runbook">x</a>', {("eng", "runbook")}),
        # Prose that merely names the path is not a link. Counting it would make
        # every page quoting a URL in its text a backlink of that page.
        ("the runbook lives at /pages/eng/runbook somewhere", set()),
        ("[a](/issues/RADD-1)", set()),
        ("no links at all", set()),
    ],
)
def test_what_counts_as_a_link(body, expected):
    slugs, _ = backlinks._targets(body)
    assert slugs == expected


def test_a_pre_702_uuid_link_still_resolves():
    """Links made before pages had slugs are `/pages/<uuid>`, and the API still
    accepts that shape — they must not silently stop counting."""
    page_id = uuid.uuid4()
    _, ids = backlinks._targets(f"[old](/pages/{page_id})")
    assert ids == {page_id}


# --- the write path keeps the index true --------------------------------------


async def test_linking_indexes_and_unlinking_removes(db, wiki):
    space, source, target, actor = wiki
    assert await _sources_of(db, target.id) == []

    await service.update_page(
        db, source.id, PageUpdate(body=f"see [it](/pages/{space.slug}/{target.slug})"), actor
    )
    assert await _sources_of(db, target.id) == [source.id]

    await service.update_page(db, source.id, PageUpdate(body="link removed"), actor)
    assert await _sources_of(db, target.id) == []


async def test_a_page_is_not_its_own_backlink(db, wiki):
    space, _, target, actor = wiki
    await service.update_page(
        db, target.id, PageUpdate(body=f"[me](/pages/{space.slug}/{target.slug})"), actor
    )
    assert await _sources_of(db, target.id) == []


async def test_a_link_to_a_page_that_does_not_exist_is_simply_not_indexed(db, wiki):
    """Writing a link before writing the page is ordinary wiki behaviour — it is
    not an error, and it must not fail the save."""
    space, source, _, actor = wiki
    await service.update_page(
        db, source.id, PageUpdate(body=f"[soon](/pages/{space.slug}/not-yet-written)"), actor
    )
    rows = await db.execute(select(PageLink).where(PageLink.source_page_id == source.id))
    assert rows.first() is None


async def test_a_rename_does_not_reindex(db, wiki):
    """Only a BODY change can change what a page links to. Reindexing on every
    save would put a delete + N inserts behind dragging a page in the tree."""
    space, source, target, actor = wiki
    await service.update_page(
        db, source.id, PageUpdate(body=f"[it](/pages/{space.slug}/{target.slug})"), actor
    )
    before = await _sources_of(db, target.id)
    await service.update_page(db, source.id, PageUpdate(title="Renamed"), actor)
    assert await _sources_of(db, target.id) == before
