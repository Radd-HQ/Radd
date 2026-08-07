"""A page's linked issues follow its text (RADD-943).

Two things are worth pinning and they fail in opposite directions. The PARSER
decides what counts as mentioning an issue: too narrow and the feature does
nothing (which is what shipped — only the editor's own token counted, so a
generated release-notes page naming twelve issues linked none of them), too wide
and a page quoting a URL in prose acquires links nobody made.

The WRITE PATH decides who owns a link. A derived row is the body's and must
vanish with the mention; a manual row is a person's and must survive any edit.
Getting that backwards destroys user data silently, so it is exercised through
the service against a real session rather than asserted about a set.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import ConflictError
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole
from radd.modules.items import service as items_service
from radd.modules.items.mentions import parse_issue_keys
from radd.modules.items.schemas import ItemCreate
from radd.modules.pages import links, service, spaces
from radd.modules.pages.models import ItemPageLink
from radd.modules.pages.schemas import PageCreate, PageSpaceCreate, PageUpdate
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


@pytest.fixture
async def wiki(db):
    """A page, and two issues in a fresh project to reference from it."""
    suffix = uuid.uuid4().hex[:8]
    actor = User(
        email=f"mn-{suffix}@example.com",
        name="Mentions",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(actor)
    await db.flush()
    space = await spaces.create_space(
        db, PageSpaceCreate(name=f"mn-{suffix}", slug=f"mn-{suffix}"), actor.id
    )
    page = await service.create_page(
        db, PageCreate(space_id=space.id, title="Notes", slug=f"notes-{suffix}"), actor.id
    )
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"MN{suffix[:4].upper()}", name="Mentions P")
    )
    one = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="First"), actor
    )
    two = await items_service.create_item(
        db, ItemCreate(project_id=project.id, title="Second"), actor
    )
    return page, actor, project, one, two


async def _links(db, page_id) -> dict[uuid.UUID, bool]:
    """{item_id: derived} for a page."""
    rows = await db.execute(
        select(ItemPageLink.item_id, ItemPageLink.derived).where(ItemPageLink.page_id == page_id)
    )
    return dict(rows.all())


# --- what counts as mentioning an issue ----------------------------------------


@pytest.mark.parametrize(
    "body, expected",
    [
        # The editor's own `#` token.
        ("see #[TD-123](TD-123)", {"TD-123"}),
        # The URL form — how a reference written outside the editor arrives, and
        # the ONLY form the generated release-notes pages use.
        ("[RADD-939](https://project.radd-hq.com/issues/RADD-939)", {"RADD-939"}),
        ("[x](/issues/AB-7)", {"AB-7"}),
        ('<a href="/issues/CD-4">x</a>', {"CD-4"}),
        # Link targets only. Prose that names a path is not a link, which is the
        # rule backlinks already sets — otherwise every page quoting a URL in a
        # code sample would acquire a link it never made.
        ("the issue lives at /issues/TD-9 somewhere", set()),
        ("[a](/pages/eng/runbook)", set()),
        ("nothing at all", set()),
    ],
)
def test_what_counts_as_an_issue_reference(body, expected):
    assert parse_issue_keys(body) == expected


def test_both_forms_in_one_body_are_deduped_by_key():
    body = "#[TD-1](TD-1) and again at [TD-1](https://example.com/issues/TD-1)"
    assert parse_issue_keys(body) == {"TD-1"}


# --- the write path owns the derived half --------------------------------------


async def test_a_mention_links_and_removing_it_unlinks(db, wiki):
    page, actor, project, one, _ = wiki
    key = f"{project.key}-{one.number}"
    assert await _links(db, page.id) == {}

    await service.update_page(db, page.id, PageUpdate(body=f"#[{key}]({key})"), actor.id)
    assert await _links(db, page.id) == {one.id: True}

    await service.update_page(db, page.id, PageUpdate(body="nothing here"), actor.id)
    assert await _links(db, page.id) == {}


async def test_a_manual_link_survives_a_body_edit_that_never_names_it(db, wiki):
    """The row records a decision someone made. Reconciling the derived half must
    not be able to reach it — this is the one failure that loses user data."""
    page, actor, project, one, _ = wiki
    await links.link_item(db, page.id, f"{project.key}-{one.number}", actor)
    await service.update_page(db, page.id, PageUpdate(body="an unrelated rewrite"), actor.id)
    assert await _links(db, page.id) == {one.id: False}


async def test_linking_something_already_mentioned_promotes_it(db, wiki):
    """Not a duplicate: the caller is asking to make the link permanent. The row
    they would be told conflicts with is one they never created."""
    page, actor, project, one, _ = wiki
    key = f"{project.key}-{one.number}"
    await service.update_page(db, page.id, PageUpdate(body=f"#[{key}]({key})"), actor.id)
    assert await _links(db, page.id) == {one.id: True}

    await links.link_item(db, page.id, key, actor)
    assert await _links(db, page.id) == {one.id: False}

    # …and it now survives the mention being deleted.
    await service.update_page(db, page.id, PageUpdate(body="mention gone"), actor.id)
    assert await _links(db, page.id) == {one.id: False}


async def test_unlinking_a_derived_link_is_refused_rather_than_undone(db, wiki):
    """Deleting it would succeed and be recreated by the next save. Saying so
    beats a control that silently does nothing."""
    page, actor, project, one, _ = wiki
    key = f"{project.key}-{one.number}"
    await service.update_page(db, page.id, PageUpdate(body=f"#[{key}]({key})"), actor.id)
    with pytest.raises(ConflictError):
        await links.unlink_item(db, page.id, one.id, actor.id)
    assert await _links(db, page.id) == {one.id: True}


async def test_a_reference_to_an_item_that_does_not_exist_is_dropped(db, wiki):
    """Typos, other instances' keys, hard-deleted issues. Ordinary text, and it
    must not fail the save."""
    page, actor, *_ = wiki
    await service.update_page(db, page.id, PageUpdate(body="#[ZZZZ-999](ZZZZ-999)"), actor.id)
    assert await _links(db, page.id) == {}


async def test_the_read_reports_where_each_link_came_from(db, wiki):
    """The UI drops the unlink button on derived rows — it can only do that if
    the flag reaches it."""
    page, actor, project, one, two = wiki
    mentioned = f"{project.key}-{one.number}"
    await links.link_item(db, page.id, f"{project.key}-{two.number}", actor)
    await service.update_page(db, page.id, PageUpdate(body=f"#[{mentioned}]({mentioned})"), actor.id)
    rows = {row.item_id: row.derived for row in await links.linked_items(db, page.id, actor)}
    assert rows == {one.id: True, two.id: False}


async def test_a_restore_reindexes(db, wiki):
    """A restore replaces the body, so the index describes the version it just
    superseded until it is rebuilt (the leg RADD-713 missed)."""
    page, actor, project, one, _ = wiki
    key = f"{project.key}-{one.number}"
    await service.update_page(db, page.id, PageUpdate(body=f"#[{key}]({key})"), actor.id)
    await service.update_page(db, page.id, PageUpdate(body="mention removed"), actor.id)
    assert await _links(db, page.id) == {}

    restored = next(v for v in await service.list_versions(db, page.id) if key in (v.body or ""))
    await service.restore_version(db, page.id, restored.version, actor.id)
    assert await _links(db, page.id) == {one.id: True}
