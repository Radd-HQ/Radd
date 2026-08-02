"""Markdown export (RADD-721).

The issue's done-when is one sentence and one property: "a space exports to a zip
of markdown files whose links still resolve relative to each other". That is the
only interesting part — writing files into a zip is not — so it is what these
test.
"""

import io
import uuid
import zipfile

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.auth.models import User
from radd.modules.pages import export, service, spaces
from radd.modules.pages.schemas import PageCreate, PageSpaceCreate
from sqlalchemy import select


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
    """A space shaped like a real one: a root with children, and cross-links."""
    actor = (await db.execute(select(User.id))).scalars().first()
    slug = f"ex-{uuid.uuid4().hex[:6]}"
    space = await spaces.create_space(db, PageSpaceCreate(name=slug, slug=slug), actor)
    handbook = await service.create_page(
        db, PageCreate(space_id=space.id, title="Handbook", slug="handbook",
                       body=f"See [the runbook](/pages/{slug}/runbook)."), actor
    )
    runbook = await service.create_page(
        db, PageCreate(space_id=space.id, parent_id=handbook.id, title="Runbook", slug="runbook",
                       body=f"Back to [the handbook](/pages/{slug}/handbook).\n\n"
                            f"An external link to [somewhere](https://example.com/pages/x/y)."), actor
    )
    return space, handbook, runbook


def _entries(blob: bytes) -> dict[str, str]:
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        return {name: archive.read(name).decode() for name in archive.namelist()}


async def test_a_space_exports_every_live_page(db, wiki):
    space, _, _ = wiki
    name, blob = await export.export_zip(db, space)
    assert name.endswith(".zip")
    entries = _entries(blob)
    # A page with children becomes a directory + index.md, so the shape on disk
    # is the shape in the tree rail.
    assert "handbook/index.md" in entries
    assert "handbook/runbook.md" in entries


async def test_the_title_survives_as_an_h1(db, wiki):
    space, _, _ = wiki
    _, blob = await export.export_zip(db, space)
    assert _entries(blob)["handbook/index.md"].startswith("# Handbook")


async def test_links_inside_the_archive_become_relative(db, wiki):
    """The done-when. An export whose links point back at the instance is a
    folder of dead ends the moment the instance is unreachable — which is the
    situation an export exists for."""
    space, _, _ = wiki
    entries = _entries((await export.export_zip(db, space))[1])
    assert "(runbook.md)" in entries["handbook/index.md"]
    assert "(index.md)" in entries["handbook/runbook.md"]


async def test_a_link_outside_the_archive_is_left_alone(db, wiki):
    """A link to a page you did not export IS a link to the instance; rewriting
    it to a relative path would invent a file that is not there."""
    space, _, _ = wiki
    entries = _entries((await export.export_zip(db, space))[1])
    assert "https://example.com/pages/x/y" in entries["handbook/runbook.md"]


async def test_exporting_one_page_takes_its_subtree(db, wiki):
    space, handbook, _ = wiki
    entries = _entries((await export.export_zip(db, space, root=handbook))[1])
    assert set(entries) == {"handbook/index.md", "handbook/runbook.md"}


async def test_a_hostile_title_still_produces_a_usable_file_name():
    """Wiki titles contain slashes and colons; an export has to survive being
    copied onto another filesystem."""
    assert "/" not in export.safe_name("Ops: incident 3/4", "x")
    assert export.safe_name("///", "fallback") == "fallback"
