"""RADD-1226: persisted conversations inherit the root's live access policy."""
import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import ConflictError, ForbiddenError, NotFoundError
from radd.modules.auth.models import User
from radd.modules.auth.scopes import parse_scope
from radd.modules.comments import service, threads
from radd.modules.comments.models import Comment
from radd.modules.comments.reading import can_read_comment
from radd.modules.comments.schemas import CommentAnchor, CommentCreate, CommentReplyCreate, CommentUpdate
from radd.modules.comments.types import CommentSlice, CommentVisibility
from radd.modules.pages import service as pages, spaces
from radd.modules.pages.schemas import PageCreate, PageSpaceCreate


@pytest.fixture
async def world():
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        author = User(email=f"thread-{uuid.uuid4()}@example.com", name="Author", instance_role="admin")
        reader = User(email=f"thread-{uuid.uuid4()}@example.com", name="Reader", instance_role="admin")
        db.add_all([author, reader])
        await db.flush()
        space = await spaces.create_space(db, PageSpaceCreate(name=f"Threads {uuid.uuid4()}", slug=f"thread-{uuid.uuid4().hex}"), author.id)
        page = await pages.create_page(db, PageCreate(space_id=space.id, title="Threaded page", body="Selected passage"), author.id)
        root = await service.create_comment(db, page.id, CommentCreate(body="A question", anchor=CommentAnchor(quote="Selected passage")), author, entity_type="page")
        yield db, author, reader, page, root
        await db.rollback()
    await engine.dispose()


async def test_replies_are_persisted_attributed_paged_and_counted_without_polluting_feeds(world):
    db, author, reader, page, root = world
    reader.token_scope = parse_scope({"global": ["page.read", "comment.write"]})
    created = [await threads.create_reply(db, root.id, CommentReplyCreate(body=f"Answer {i}"), reader) for i in range(5)]
    assert all(reply.author.id == reader.id and reply.parent_comment_id == root.id and reply.anchor is None for reply in created)
    first = await threads.reply_page(db, root.id, author, limit=2)
    second = await threads.reply_page(db, root.id, author, limit=2, before=first.older_cursor)
    third = await threads.reply_page(db, root.id, author, limit=2, before=second.older_cursor)
    expected = sorted(created, key=lambda reply: (reply.created_at, reply.id))
    assert [reply.id for reply in third.comments + second.comments + first.comments] == [reply.id for reply in expected]
    assert third.older_cursor is None
    for read in (service.list_comments, service.comment_page):
        result = await read(db, page.id, author, entity_type="page")
        rows = result.comments if hasattr(result, "comments") else result
        assert [(row.id, row.reply_count) for row in rows] == [(root.id, 5)]
    discussion = await service.comment_page(db, page.id, author, entity_type="page", section=CommentSlice.DISCUSSION)
    assert discussion.comments == []
    assert await can_read_comment(db, created[0].id, reader)
    with pytest.raises(NotFoundError):
        await threads.create_reply(db, created[0].id, CommentReplyCreate(body="nested"), reader)


async def test_reply_requires_both_read_and_write_and_hidden_roots_do_not_leak(world):
    db, author, reader, page, root = world
    reader.token_scope = parse_scope({"global": ["page.read"]})
    assert (await threads.reply_page(db, root.id, reader)).comments == []
    with pytest.raises(ForbiddenError):
        await threads.create_reply(db, root.id, CommentReplyCreate(body="No write permission"), reader)
    private = await service.create_comment(db, page.id, CommentCreate(body="Secret", anchor=CommentAnchor(quote="passage"), visibility=CommentVisibility.INTERNAL), author, entity_type="page")
    reply = await threads.create_reply(db, private.id, CommentReplyCreate(body="Secret answer"), author)
    for action in (lambda: threads.reply_page(db, private.id, reader),
                   lambda: threads.create_reply(db, private.id, CommentReplyCreate(body="Probe"), reader)):
        with pytest.raises(NotFoundError):
            await action()
    assert not await can_read_comment(db, reply.id, reader)
    reader.token_scope = parse_scope({"global": ["comment.write"]})
    with pytest.raises(ForbiddenError):
        await threads.reply_page(db, root.id, reader)


async def test_resolution_reopen_and_cascade_preserve_the_conversation(world):
    db, author, reader, page, root = world
    reply = await threads.create_reply(db, root.id, CommentReplyCreate(body="Keep this answer"), reader)
    resolved = await service.set_resolved(db, root.id, author, resolved=True)
    assert resolved.resolver_name == "Author"
    assert (await threads.reply_page(db, root.id, reader)).comments[0].id == reply.id
    # A resolved thread takes a reply and stays resolved (GitLab's plain "Reply")…
    await threads.create_reply(db, root.id, CommentReplyCreate(body="After the fact"), reader)
    listed = (await service.comment_page(db, page.id, author, entity_type="page")).comments
    assert listed[0].resolved_at is not None and listed[0].resolver_name == "Author"
    with pytest.raises(ConflictError):
        await service.set_resolved(db, reply.id, reader, resolved=True)
    # …and "Reply and unresolve" reopens it in the same write.
    await threads.create_reply(db, root.id, CommentReplyCreate(body="Not done", unresolve=True), author)
    reopened = (await service.comment_page(db, page.id, author, entity_type="page")).comments[0]
    assert reopened.resolved_at is None and reopened.resolver_name is None and reopened.reply_count == 3
    # RADD-1246: a reply may be edited within its thread's audience — on a
    # public thread an empty team list is that audience, so this is allowed.
    edited = await service.update_comment(db, reply.id, CommentUpdate(body="Edited within audience", visible_to_teams=[]), reader)
    assert edited.visibility is CommentVisibility.PUBLIC and edited.visible_to_teams == []
    await service.delete_comment(db, root.id, author)
    await db.flush()
    assert (await db.scalars(select(Comment.id).where(Comment.parent_comment_id == root.id))).all() == []


async def test_http_reply_contract_ignores_author_spoof_and_rejects_bad_requests(world):
    from radd.app import create_app
    from radd.db import get_session
    from radd.modules.auth.deps import current_user, actor

    db, author, reader, page, root = world
    app = create_app()
    async def session_override():
        yield db
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[current_user] = lambda: reader
    app.dependency_overrides[actor] = lambda: reader
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        url = f"/api/v1/comments/{root.id}/replies"
        posted = await client.post(url, json={"body": "HTTP reply", "author_id": str(author.id)})
        assert posted.status_code == 201, posted.text
        assert posted.json()["author"]["id"] == str(reader.id)
        assert (await client.get(url)).json()["comments"][0]["body"] == "HTTP reply"
        for payload in ({"body": ""}, {"body": "   "}):
            assert (await client.post(url, json=payload)).status_code == 422
        for query in ("?limit=0", "?limit=201", "?before=invalid"):
            assert (await client.get(url + query)).status_code == 422
        reader.token_scope = parse_scope({"global": ["page.read"]})
        assert (await client.post(url, json={"body": "Forbidden"})).status_code == 403


async def test_anonymous_reply_reads_follow_public_space_and_root_visibility(world):
    from radd.app import create_app
    from radd.db import get_session
    from radd.modules.auth import principals, public_access, roles

    db, author, reader, page, root = world
    await roles.ensure_builtin_roles(db)
    await principals.ensure_principals(db)
    await threads.create_reply(db, root.id, CommentReplyCreate(body="Public answer"), author)
    private = await service.create_comment(db, page.id, CommentCreate(body="Private annotation",
        anchor=CommentAnchor(quote="passage"), visibility=CommentVisibility.INTERNAL), author, entity_type="page")
    await threads.create_reply(db, private.id, CommentReplyCreate(body="Private answer"), author)
    app = create_app()
    async def session_override():
        yield db
    app.dependency_overrides[get_session] = session_override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        url = f"/api/v1/comments/{root.id}/replies"
        assert (await client.get(url)).status_code in (403, 404)
        await public_access.set_space_public(db, page.space_id, public=True, actor_id=author.id)
        db.info.clear()  # a new request has a fresh permission cache
        public = await client.get(url)
        assert public.status_code == 200, public.text
        assert public.json()["comments"][0]["body"] == "Public answer"
        assert (await client.get(f"/api/v1/comments/{private.id}/replies")).status_code == 404
        assert (await client.post(url, json={"body": "Anonymous write"})).status_code == 401
        await public_access.set_space_public(db, page.space_id, public=False, actor_id=author.id)
        db.info.clear()
        assert (await client.get(url)).status_code in (403, 404)
