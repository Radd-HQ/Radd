"""Page comments (RADD-717) — the polymorphic parent.

The invariants worth pinning are the ones a column rename would quietly break:
an item comment must behave exactly as before, a page comment must not leak into
anything item-shaped, and neither may outlive its parent now that the foreign
key (and its CASCADE) is gone.
"""

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.auth.models import User
from radd.modules.comments import service as comments
from radd.modules.comments.models import Comment
from radd.modules.comments.parents import binding_for, registered_types
from radd.modules.comments.schemas import CommentCreate
from radd.modules.comments.types import CommentParentType
from radd.modules.pages import service as pages_service, spaces
from radd.modules.pages.schemas import PageCreate, PageSpaceCreate


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def admin(db):
    user = User(email=f"pc-{uuid.uuid4().hex[:8]}@example.com", name="PC", instance_role="admin")
    db.add(user)
    await db.flush()
    return user


@pytest.fixture
async def page(db, admin):
    space = await spaces.create_space(
        db, PageSpaceCreate(name=f"pc-{uuid.uuid4().hex[:6]}", slug=f"pc-{uuid.uuid4().hex[:6]}"),
        admin.id,
    )
    return await pages_service.create_page(
        db, PageCreate(space_id=space.id, title="Decision", body="why we chose this"), admin.id
    )


# --- the registry --------------------------------------------------------------


def test_both_parents_are_registered():
    assert set(registered_types()) >= {"item", "page"}


def test_an_unknown_parent_type_is_a_404_not_a_crash():
    from radd.exceptions import NotFoundError

    with pytest.raises(NotFoundError):
        binding_for("spaceship")


async def test_a_page_has_no_project_and_that_is_not_an_error(db, page):
    """The whole reason this needed a binding: a page is global, so the
    permission checks run at global scope rather than against a project."""
    binding = binding_for(CommentParentType.PAGE.value)
    assert await binding.project_of(db, page.id) is None


# --- behaviour -----------------------------------------------------------------


async def test_a_page_can_hold_a_discussion(db, admin, page):
    read = await comments.create_comment(
        db, page.id, CommentCreate(body="I disagree, and here is why"),
        actor=admin, entity_type=CommentParentType.PAGE.value,
    )
    assert read.entity_type == "page"
    assert read.entity_id == page.id
    # `item_id` is null for a non-item parent, so an issue-side consumer that
    # reads it gets nothing rather than a page id it would misuse.
    assert read.item_id is None

    listed = await comments.list_comments(
        db, page.id, actor=admin, entity_type=CommentParentType.PAGE.value
    )
    assert [c.body for c in listed] == ["I disagree, and here is why"]


async def test_page_comments_do_not_appear_on_items(db, admin, page):
    """A page id and an item id are both uuids. Without the type in the
    predicate, a collision would surface someone's page discussion on an issue."""
    await comments.create_comment(
        db, page.id, CommentCreate(body="page talk"), actor=admin,
        entity_type=CommentParentType.PAGE.value,
    )
    counts = await comments.comment_counts(db, [page.id], include_internal=True)
    assert counts.get(page.id) is None


async def test_commented_by_slq_stays_item_only(db, admin, page):
    """`commented_by` is an ITEM-dialect field; a page comment must not put a
    page id into an item query's id set."""
    await comments.create_comment(
        db, page.id, CommentCreate(body="x"), actor=admin,
        entity_type=CommentParentType.PAGE.value,
    )
    rows = await db.execute(
        select(Comment.entity_id).where(Comment.entity_type == CommentParentType.ITEM)
    )
    assert page.id not in set(rows.scalars())


async def test_deleting_the_page_takes_its_comments(db, admin, page):
    """The polymorphic column carries no FK, so the CASCADE is gone and the
    delete path has to sweep. Without this a deleted page leaves comments
    nothing can reach and nothing can remove."""
    await comments.create_comment(
        db, page.id, CommentCreate(body="doomed"), actor=admin,
        entity_type=CommentParentType.PAGE.value,
    )
    await pages_service.archive_page(db, page.id, admin.id)
    await pages_service.hard_delete_page(db, page.id, admin.id)
    left = await db.execute(
        select(Comment).where(
            Comment.entity_type == CommentParentType.PAGE, Comment.entity_id == page.id
        )
    )
    assert left.first() is None


async def test_the_stored_shape_is_the_wire_shape(db, admin, page):
    """`entity_type` is a wire format — it is in the column and in event
    payloads — so it must be the enum's value, not a stringified member."""
    await comments.create_comment(
        db, page.id, CommentCreate(body="y"), actor=admin,
        entity_type=CommentParentType.PAGE.value,
    )
    stored = await db.execute(
        text("SELECT DISTINCT entity_type FROM comments WHERE entity_id = :i"), {"i": page.id}
    )
    assert stored.scalars().all() == ["page"]


# --- RADD-726: inline anchors and resolution ----------------------------------


async def test_an_inline_comment_stores_its_anchor(db, admin, page):
    from radd.modules.comments.schemas import CommentAnchor

    read = await comments.create_comment(
        db, page.id,
        CommentCreate(
            body="is this still true?",
            anchor=CommentAnchor(quote="why we chose", prefix="", suffix=" this"),
        ),
        actor=admin, entity_type=CommentParentType.PAGE.value,
    )
    assert read.anchor is not None and read.anchor.quote == "why we chose"
    assert read.resolved_at is None


async def test_resolve_and_reopen(db, admin, page):
    """This exists because a NameError in `set_resolved` reached a running
    server: nothing in the suite called it, so a green run and a 500 coexisted.
    A test that EXECUTES the path is the only thing that catches that."""
    from radd.modules.comments.schemas import CommentAnchor

    read = await comments.create_comment(
        db, page.id,
        CommentCreate(body="x", anchor=CommentAnchor(quote="why", prefix="", suffix="")),
        actor=admin, entity_type=CommentParentType.PAGE.value,
    )
    resolved = await comments.set_resolved(db, read.id, admin, resolved=True)
    assert resolved.resolved_at is not None
    assert resolved.resolved_by == admin.id

    # Idempotent: two people clicking at once is ordinary, not an error.
    again = await comments.set_resolved(db, read.id, admin, resolved=True)
    assert again.resolved_at is not None

    reopened = await comments.set_resolved(db, read.id, admin, resolved=False)
    assert reopened.resolved_at is None and reopened.resolved_by is None


async def test_an_ordinary_thread_comment_has_no_anchor(db, admin, page):
    """The compatibility story: every comment that exists today is exactly this."""
    read = await comments.create_comment(
        db, page.id, CommentCreate(body="general remark"),
        actor=admin, entity_type=CommentParentType.PAGE.value,
    )
    assert read.anchor is None and read.resolved_at is None


# --- RADD-719: watching a page ------------------------------------------------


async def test_editing_a_page_notifies_its_watchers_but_not_the_editor(db, admin, page):
    """The point of the feature: a silently changed runbook is the failure mode
    for a wiki that documents operations. And nobody wants an inbox entry telling
    them about their own edit."""
    from radd.modules.notify.models import Notification
    from radd.modules.pages import watchers
    from radd.modules.pages.schemas import PageUpdate

    watcher = User(email=f"w-{uuid.uuid4().hex[:8]}@example.com", name="Watcher")
    db.add(watcher)
    await db.flush()
    await watchers.watch(db, page.id, watcher.id)
    await watchers.watch(db, page.id, admin.id)

    await pages_service.update_page(db, page.id, PageUpdate(body="rewritten"), admin.id)

    rows = await db.execute(
        select(Notification).where(Notification.user_id == watcher.id)
    )
    delivered = rows.scalars().all()
    assert len(delivered) == 1
    assert delivered[0].payload["title"] == page.title
    assert delivered[0].payload["page_slug"] == page.slug

    mine = await db.execute(select(Notification).where(Notification.user_id == admin.id))
    assert mine.first() is None  # the editor is not told about their own edit


async def test_editing_auto_watches_the_editor(db, admin, page):
    from radd.modules.pages import watchers
    from radd.modules.pages.schemas import PageUpdate

    assert await watchers.is_watching(db, page.id, admin.id) is False
    await pages_service.update_page(db, page.id, PageUpdate(body="touched"), admin.id)
    assert await watchers.is_watching(db, page.id, admin.id) is True


async def test_watching_twice_is_a_double_click_not_an_error(db, admin, page):
    from radd.modules.pages import watchers

    await watchers.watch(db, page.id, admin.id)
    await watchers.watch(db, page.id, admin.id)
    assert await watchers.watcher_ids(db, page.id) == [admin.id]
    await watchers.unwatch(db, page.id, admin.id)
    assert await watchers.watcher_ids(db, page.id) == []


# --- the orphan GC: what replaces ON DELETE CASCADE ---------------------------


def test_every_registered_parent_declares_how_it_dies():
    """The guard that makes the polymorphic parent safe to extend.

    A plugin registering a `CommentParent` gets cleanup for free — but only
    because the GC builds its event map from the registry. A binding with no
    `deleted_event` would leave its comments orphaned forever, invisibly. This
    fails the build instead."""
    from radd.modules.comments.parents import bindings

    registered = bindings()
    assert registered, "no comment parents registered at all"
    for binding in registered:
        assert binding.deleted_event, f"{binding.entity_type} declares no delete event"
        assert binding.deleted_event.endswith(".deleted")


def test_the_gc_map_covers_every_parent():
    from radd.modules.comments.gc import _parent_deletes
    from radd.modules.comments.parents import bindings

    covered = set(_parent_deletes().values())
    assert covered == {binding.entity_type for binding in bindings()}


async def test_the_gc_sweeps_a_comment_whose_parent_bypassed_the_delete_path(db, admin, page):
    """The case the explicit sweep cannot cover: a parent removed by something
    that never called `delete_for_parent`. Simulated by deleting the page row
    directly, which is what any future path that forgets will look like."""
    from radd.modules.comments import gc
    from radd.modules.comments.models import Comment
    from radd.modules.events.models import Event
    from radd.modules.pages.models import Page

    await comments.create_comment(
        db, page.id, CommentCreate(body="orphan me"), actor=admin,
        entity_type=CommentParentType.PAGE.value,
    )
    await db.execute(text("DELETE FROM pages WHERE id = :i"), {"i": page.id})
    left = await db.execute(
        select(Comment).where(Comment.entity_id == page.id)
    )
    assert left.first() is not None  # no cascade — this is the gap being closed

    await gc._plan(db, Event(event_type="page.deleted", entity_id=str(page.id), payload={}))
    swept = await db.execute(select(Comment).where(Comment.entity_id == page.id))
    assert swept.first() is None
