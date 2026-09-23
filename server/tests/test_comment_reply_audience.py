"""Replies on every comment surface, each with an audience bounded by its
thread's (RADD-1246):

- an INTERNAL thread forces internal replies (a public one is refused) and
  lets a reply only NARROW the thread's teams;
- a PUBLIC thread takes public replies and internal ones, and the internal
  ones are invisible to a reader who may not read internal comments;
- narrowing an internal root pulls its wider replies in;
- an issue comment, a page's general discussion and an annotation are all
  roots; a reply to a reply is still refused.

DB-backed, flushed never committed. Scoped keys stand in for less-privileged
people: an admin whose token scope lacks `comment.read_internal` reads exactly
what a member without the atom reads.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.exceptions import ConflictError, NotFoundError
from radd.modules.auth.models import User
from radd.modules.auth.scopes import parse_scope
from radd.modules.comments import service, threads
from radd.modules.comments.reading import can_read_comment
from radd.modules.comments.schemas import CommentCreate, CommentReplyCreate, CommentUpdate
from radd.modules.comments.types import CommentVisibility
from radd.modules.items import service as items
from radd.modules.items.schemas import ItemCreate
from radd.modules.mcp import tools
from radd.modules.pages import service as pages, spaces
from radd.modules.pages.schemas import PageCreate, PageSpaceCreate
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.teams import service as teams_service
from radd.modules.teams.schemas import TeamCreate

INTERNAL, PUBLIC = CommentVisibility.INTERNAL, CommentVisibility.PUBLIC


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _admin(db, name: str, *, scope: list[str] | None = None) -> User:
    user = User(email=f"reply-{uuid.uuid4().hex[:8]}@example.com", name=name, instance_role="admin")
    db.add(user)
    await db.flush()
    if scope is not None:
        user.token_scope = parse_scope({"global": scope})
    return user


async def _item(db, actor):
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"RA{uuid.uuid4().hex[:4].upper()}", name="Reply audience")
    )
    return await items.create_item(db, ItemCreate(project_id=project.id, title="threaded"), actor)


async def test_internal_thread_forces_internal_replies_and_only_narrows(db):
    manager = await _admin(db, "Manager")
    item = await _item(db, manager)
    desk = await teams_service.create_team(db, TeamCreate(name=f"Desk {uuid.uuid4().hex[:5]}"))
    other = await teams_service.create_team(db, TeamCreate(name=f"Other {uuid.uuid4().hex[:5]}"))
    root = await service.create_comment(
        db, item.id, CommentCreate(body="internal root", visibility=INTERNAL, visible_to_teams=[desk.id]), manager
    )

    with pytest.raises(ConflictError):
        await threads.create_reply(db, root.id, CommentReplyCreate(body="leak", visibility=PUBLIC), manager)
    with pytest.raises(ConflictError):
        await threads.create_reply(
            db, root.id, CommentReplyCreate(body="wider", visible_to_teams=[desk.id, other.id]), manager
        )
    inherited = await threads.create_reply(db, root.id, CommentReplyCreate(body="inherits"), manager)
    assert inherited.visibility is INTERNAL and inherited.visible_to_teams == [desk.id]
    # Explicitly asking for internal within the thread's teams is the same thing.
    explicit = await threads.create_reply(
        db, root.id, CommentReplyCreate(body="explicit", visibility=INTERNAL, visible_to_teams=[desk.id]), manager
    )
    assert explicit.visible_to_teams == [desk.id]
    # An edit cannot widen either.
    with pytest.raises(ConflictError):
        await service.update_comment(db, explicit.id, CommentUpdate(body="x", visible_to_teams=[other.id]), manager)


async def test_public_thread_takes_an_internal_reply_that_non_readers_cannot_see(db):
    manager = await _admin(db, "Manager")
    writer = await _admin(db, "Writer", scope=["item.read", "comment.write"])
    item = await _item(db, manager)
    root = await service.create_comment(db, item.id, CommentCreate(body="public root"), writer)

    public = await threads.create_reply(db, root.id, CommentReplyCreate(body="seen by all"), writer)
    internal = await threads.create_reply(
        db, root.id, CommentReplyCreate(body="staff only", visibility=INTERNAL), manager
    )
    assert public.visibility is PUBLIC and internal.visibility is INTERNAL

    # The writer holds no comment.read_internal: the reply list and the count
    # both answer what THEY may read, and the deferred-delivery gate agrees.
    page = await threads.reply_page(db, root.id, writer)
    assert [reply.id for reply in page.comments] == [public.id]
    assert [c.reply_count for c in await service.list_comments(db, item.id, writer)] == [1]
    assert await can_read_comment(db, public.id, writer)
    assert not await can_read_comment(db, internal.id, writer)

    everything = await threads.reply_page(db, root.id, manager)
    assert {reply.id for reply in everything.comments} == {public.id, internal.id}
    assert [c.reply_count for c in await service.list_comments(db, item.id, manager)] == [2]
    assert await can_read_comment(db, internal.id, manager)

    # A writer without the atom cannot post an internal reply either.
    from radd.exceptions import ForbiddenError
    with pytest.raises(ForbiddenError):
        await threads.create_reply(db, root.id, CommentReplyCreate(body="no", visibility=INTERNAL), writer)


async def test_narrowing_an_internal_root_pulls_its_replies_in(db):
    manager = await _admin(db, "Manager")
    item = await _item(db, manager)
    desk = await teams_service.create_team(db, TeamCreate(name=f"Desk {uuid.uuid4().hex[:5]}"))
    root = await service.create_comment(db, item.id, CommentCreate(body="root", visibility=INTERNAL), manager)
    wide = await threads.create_reply(db, root.id, CommentReplyCreate(body="every internal reader"), manager)
    assert wide.visible_to_teams == []

    await service.update_comment(db, root.id, CommentUpdate(body="root", visible_to_teams=[desk.id]), manager)
    narrowed = (await threads.reply_page(db, root.id, manager)).comments
    assert [reply.visible_to_teams for reply in narrowed] == [[desk.id]]


async def test_every_surface_is_a_root_and_replies_stay_flat(db):
    manager = await _admin(db, "Manager")
    item = await _item(db, manager)
    issue_root = await service.create_comment(db, item.id, CommentCreate(body="issue comment"), manager)
    issue_reply = await threads.create_reply(db, issue_root.id, CommentReplyCreate(body="issue reply"), manager)
    with pytest.raises(NotFoundError):
        await threads.create_reply(db, issue_reply.id, CommentReplyCreate(body="nested"), manager)
    assert [(c.id, c.reply_count) for c in await service.list_comments(db, item.id, manager)] == [(issue_root.id, 1)]

    space = await spaces.create_space(
        db, PageSpaceCreate(name=f"Replies {uuid.uuid4().hex[:5]}", slug=f"replies-{uuid.uuid4().hex}"), manager.id
    )
    page = await pages.create_page(db, PageCreate(space_id=space.id, title="Discussed", body="text"), manager.id)
    discussion = await service.create_comment(db, page.id, CommentCreate(body="general"), manager, entity_type="page")
    assert discussion.anchor is None
    reply = await threads.create_reply(db, discussion.id, CommentReplyCreate(body="answer"), manager)
    assert reply.parent_comment_id == discussion.id
    assert [(c.id, c.reply_count) for c in await service.list_comments(db, page.id, manager, entity_type="page")] == [
        (discussion.id, 1)
    ]


async def test_mcp_comment_item_replies_under_a_comment_of_the_same_item(db):
    manager = await _admin(db, "Manager")
    item = await _item(db, manager)
    stranger = await _item(db, manager)
    root = await service.create_comment(db, item.id, CommentCreate(body="root"), manager)
    posted = await tools.call_tool(
        db, manager, "comment_item", {"key": item.key, "body": "over MCP", "reply_to": str(root.id)}
    )
    assert posted["reply_to"] == str(root.id)
    replies = (await threads.reply_page(db, root.id, manager)).comments
    assert [reply.body for reply in replies] == ["over MCP"]
    # A comment of ANOTHER item is not a thread of this one.
    with pytest.raises(NotFoundError):
        await tools.call_tool(
            db, manager, "comment_item", {"key": stranger.key, "body": "wrong item", "reply_to": str(root.id)}
        )


async def test_resolvable_thread_requires_live_read_and_resolution_permission(db):
    from radd.exceptions import ForbiddenError

    manager = await _admin(db, "Manager")
    reader = await _admin(db, "Reader", scope=["item.read", "comment.write"])
    item = await _item(db, manager)
    root = await service.create_comment(db, item.id, CommentCreate(
        body="Restricted review", visibility=INTERNAL, is_thread=True), manager)
    assert await service.has_unresolved_threads(db, item.id)
    assert not (await service.comment_page(db, item.id, reader, unresolved=True)).comments
    with pytest.raises(NotFoundError):
        await service.set_resolved(db, root.id, reader, resolved=True)
    public = await service.create_comment(db, item.id, CommentCreate(body="Public review", is_thread=True), manager)
    with pytest.raises(ForbiddenError):
        await service.set_resolved(db, public.id, reader, resolved=True)
    own = await service.create_comment(db, item.id, CommentCreate(body="My review", is_thread=True), reader)
    assert (await service.set_resolved(db, own.id, reader, resolved=True)).resolved_by == reader.id
    reader.token_scope = parse_scope({"global": ["item.read"]})
    with pytest.raises(ForbiddenError):
        await service.set_resolved(db, own.id, reader, resolved=False)


async def test_thread_migration_preserves_sql_and_json_null_comments(db):
    """Ordinary JSONB anchors are JSON null, not SQL NULL: never backfill them."""
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text

    path = Path(__file__).parents[1] / "migrations/versions/d1282threads_resolvable_discussions.py"
    spec = importlib.util.spec_from_file_location("thread_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    await db.execute(text("CREATE TEMP TABLE comments (id integer, entity_type text, entity_id uuid, anchor jsonb, resolved_at timestamp, parent_comment_id integer) ON COMMIT DROP"))
    await db.execute(text("""INSERT INTO comments (id, anchor, resolved_at, parent_comment_id) VALUES
        (1, NULL, NULL, NULL), (2, 'null', NULL, NULL),
        (3, '{"quote":"passage"}', NULL, NULL), (4, 'null', now(), NULL),
        (5, 'null', NULL, 3)"""))
    connection = await db.connection()
    def upgrade(sync_connection):
        with Operations.context(MigrationContext.configure(sync_connection)):
            migration.upgrade()
    await connection.run_sync(upgrade)
    rows = (await db.execute(text("SELECT id, is_thread FROM comments ORDER BY id"))).all()
    assert rows == [(1, False), (2, False), (3, True), (4, True), (5, False)]
    await db.execute(text("INSERT INTO comments (id) VALUES (6)"))
    assert await db.scalar(text("SELECT is_thread FROM comments WHERE id = 6")) is False
