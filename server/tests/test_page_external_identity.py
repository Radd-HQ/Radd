"""A page remembers where it came from (spec 117, RADD-1012).

The Jira importer never needed this: it maps `DEV-123` onto Radd `DEV-123`, so
the item KEY is the external identity and a re-import upserts on it. A page has
only a UUID and a cosmetic slug, so the mapping needs a column — otherwise it
lives in an importer's run ledger, which one rollback deletes.

The gate matters as much as the column. `create_page` is the door every page comes
through, and an ordinary request must not reach the author/timestamp overrides by
adding two fields to its JSON body — so they are honored only for a caller that
passes a permission set carrying `page.manage`, exactly as
`comments.create_authorized_comment` gates its own.
"""

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import ForbiddenError
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole, Permission
from radd.modules.pages import service as pages_service, spaces
from radd.modules.pages.schemas import PageCreate, PageSpaceCreate, PageUpdate

IMPORTING = frozenset({Permission.PAGE_MANAGE})
SOURCE = "confluence:wiki.example.com"


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()


async def _people(db) -> tuple[User, User]:
    """The actor running the import, and the person who actually wrote the page —
    the whole point of the author override is that these differ."""
    actor = User(
        email=f"actor-{uuid.uuid4().hex[:8]}@example.com",
        name="Importer",
        instance_role=InstanceRole.ADMIN.value,
    )
    author = User(
        email=f"author-{uuid.uuid4().hex[:8]}@example.com",
        name="Original Author",
        instance_role=InstanceRole.MEMBER.value,
    )
    db.add_all([actor, author])
    await db.flush()
    return actor, author


async def _space(db, actor):
    return await spaces.create_space(
        db, PageSpaceCreate(name=f"Space {uuid.uuid4().hex[:6]}"), actor.id
    )


# --- the gate ---


async def test_overrides_are_ignored_without_page_manage(db):
    """The default call — every router path — must be unable to reach them."""
    actor, author = await _people(db)
    space = await _space(db, actor)
    long_ago = datetime(2014, 3, 2, tzinfo=timezone.utc)

    page = await pages_service.create_page(
        db,
        PageCreate(
            space_id=space.id,
            title="Ordinary",
            author_id=author.id,
            created_at=long_ago,
            external_source=SOURCE,
            external_id="12345",
        ),
        actor.id,
    )

    assert page.created_by == actor.id, "an unprivileged caller cannot forge authorship"
    assert page.external_id == "", "nor claim a foreign identity"
    assert page.created_at.year != 2014, "nor backdate"


async def test_overrides_are_honored_for_an_importer(db):
    actor, author = await _people(db)
    space = await _space(db, actor)
    written = datetime(2014, 3, 2, 9, 30, tzinfo=timezone.utc)

    page = await pages_service.create_page(
        db,
        PageCreate(
            space_id=space.id,
            title="Imported",
            author_id=author.id,
            created_at=written,
            external_source=SOURCE,
            external_id="12345",
        ),
        actor.id,
        permissions=IMPORTING,
    )

    assert page.created_by == author.id
    assert page.updated_by == author.id
    assert page.created_at.replace(tzinfo=None) == written.replace(tzinfo=None)
    # updated_at follows created_at when the caller names only the one — a page
    # imported as "created in 2014, modified today" would read as recently edited.
    assert page.updated_at.replace(tzinfo=None) == written.replace(tzinfo=None)
    assert (page.external_source, page.external_id) == (SOURCE, "12345")


# --- the lookup that makes re-import an upsert ---


async def test_find_by_external_round_trips(db):
    actor, _ = await _people(db)
    space = await _space(db, actor)
    page = await pages_service.create_page(
        db,
        PageCreate(
            space_id=space.id, title="Findable",
            external_source=SOURCE, external_id="777",
        ),
        actor.id,
        permissions=IMPORTING,
    )

    found = await pages_service.find_by_external(db, SOURCE, "777")
    assert found is not None and found.id == page.id
    # Source-qualified: another instance's page 777 is a different page.
    assert await pages_service.find_by_external(db, "confluence:other.example.com", "777") is None
    assert await pages_service.find_by_external(db, SOURCE, "does-not-exist") is None


async def test_find_by_external_ignores_the_empty_pair(db):
    """Every natively-created page shares the empty identity. Asking for it must
    not return an arbitrary one of them."""
    actor, _ = await _people(db)
    space = await _space(db, actor)
    await pages_service.create_page(db, PageCreate(space_id=space.id, title="Native"), actor.id)

    assert await pages_service.find_by_external(db, "", "") is None


async def test_native_pages_do_not_collide_on_the_empty_pair(db):
    """The unique index is PARTIAL; a plain one would let exactly one native page
    exist per space tree."""
    actor, _ = await _people(db)
    space = await _space(db, actor)
    for title in ("One", "Two", "Three"):
        await pages_service.create_page(db, PageCreate(space_id=space.id, title=title), actor.id)
    await db.flush()  # the index is enforced here, not at create


async def test_space_external_identity_round_trips(db):
    """Re-importing a space must land in the space it made, not "Space PIP (2)"."""
    actor, _ = await _people(db)
    space = await spaces.create_space(
        db,
        PageSpaceCreate(
            name="Pipeline", external_source=SOURCE, external_id="PIP",
        ),
        actor.id,
        permissions=IMPORTING,
    )
    found = await spaces.find_space_by_external(db, SOURCE, "PIP")
    assert found is not None and found.id == space.id


# --- history ---


async def test_write_version_refuses_without_page_manage(db):
    actor, author = await _people(db)
    space = await _space(db, actor)
    page = await pages_service.create_page(
        db, PageCreate(space_id=space.id, title="P"), actor.id
    )
    with pytest.raises(ForbiddenError):
        await pages_service.write_version(
            db, page.id, version=1, title="P", body="old", author_id=author.id
        )


async def test_write_version_records_the_original_author_and_date(db):
    """The entire reason to import history: rows attributed to who wrote them."""
    actor, author = await _people(db)
    space = await _space(db, actor)
    page = await pages_service.create_page(
        db, PageCreate(space_id=space.id, title="P", body="current"), actor.id
    )
    then = datetime(2016, 7, 1, 12, tzinfo=timezone.utc)

    await pages_service.write_version(
        db, page.id,
        version=1, title="P", body="the original text",
        author_id=author.id, created_at=then, permissions=IMPORTING,
    )

    versions = await pages_service.list_versions(db, page.id)
    assert [v.version for v in versions] == [1]
    assert versions[0].author_id == author.id
    assert versions[0].body == "the original text"
    assert versions[0].created_at.replace(tzinfo=None) == then.replace(tzinfo=None)


async def test_update_credits_the_revisions_editor_for_an_importer(db):
    actor, author = await _people(db)
    space = await _space(db, actor)
    page = await pages_service.create_page(
        db, PageCreate(space_id=space.id, title="P", body="v1"), actor.id
    )
    edited = datetime(2018, 1, 5, tzinfo=timezone.utc)

    await pages_service.update_page(
        db, page.id,
        PageUpdate(body="v2", author_id=author.id, updated_at=edited),
        actor.id,
        permissions=IMPORTING,
    )

    assert page.updated_by == author.id
    assert page.updated_at.replace(tzinfo=None) == edited.replace(tzinfo=None)
    assert page.version == 2
