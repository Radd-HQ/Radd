"""An existing comment becomes a resolvable thread after the fact (RADD-1478,
GitHub #35): `is_thread` on PATCH — true for a top-level comment (never a
reply), emitting the comment's UPDATED event with the change so the workflow
guard, the unresolved feed and automations see a thread; false only while the
thread is unresolved and nobody has answered. The same over MCP. Rolled back.
"""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from _factories import make_project, make_user
from radd.exceptions import ConflictError, ForbiddenError
from radd.modules.auth import roles as auth_roles
from radd.modules.auth.models import GlobalRoleGrant
from radd.modules.auth.types import BuiltinRoleKey, InstanceRole
from radd.modules.comments import service, threads
from radd.modules.comments.mcptools import UPDATE_COMMENT
from radd.modules.comments.models import Comment
from radd.modules.comments.schemas import CommentAnchor, CommentCreate, CommentReplyCreate, CommentUpdate
from radd.modules.comments.types import CommentEntity, CommentEvent
from radd.kernel.changes import CHANGES_KEY
from radd.modules.events.models import Event
from radd.modules.items import service as items
from radd.modules.items.schemas import ItemCreate
from radd.modules.mcp import tools
from radd.modules.pages import service as pages, spaces
from radd.modules.pages.schemas import PageCreate, PageSpaceCreate


@pytest.fixture
async def rig(db):
    """The author's plain comment on an admin's item; a stranger who is a member by role."""
    admin = await make_user(db, role=InstanceRole.ADMIN, name="Admin")
    author, stranger = [await make_user(db, name=n) for n in ("Author", "Stranger")]
    await auth_roles.ensure_builtin_roles(db)
    project = await make_project(db, "TC", "Thread conversion")
    member = await auth_roles.role_by_key(db, BuiltinRoleKey.MEMBER)
    db.add_all([GlobalRoleGrant(project_id=project.id, user_id=u.id, role_id=member.id) for u in (author, stranger)])
    await db.flush()
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="conversion rig"), admin)
    comment = await service.create_comment(db, item.id, CommentCreate(body="Is this right?"), author)
    return SimpleNamespace(admin=admin, author=author, stranger=stranger, item=item, comment=comment)


async def _thread_changes(db, comment_id) -> list[dict]:
    """The `is_thread` entries across the comment's UPDATED events."""
    rows = (await db.scalars(select(Event).where(
        Event.entity_type == CommentEntity.COMMENT.value, Event.entity_id == str(comment_id),
        Event.event_type == CommentEvent.UPDATED.value,
    ))).all()
    return [c for row in rows for c in (row.payload.get(CHANGES_KEY) or []) if c.get("field") == "is_thread"]


async def test_a_comment_becomes_an_unresolved_thread_that_the_guard_feed_and_events_see(db, rig):
    assert not await threads.has_unresolved_threads(db, rig.item.id)
    read = await service.update_comment(db, rig.comment.id, CommentUpdate(is_thread=True), rig.author)
    assert read.is_thread and read.resolved_at is None and read.body == "Is this right?"
    assert read.can_resolve  # the author, under the default rule — the row redraws with its controls
    assert await threads.has_unresolved_threads(db, rig.item.id)
    unresolved = await service.comment_page(db, rig.item.id, rig.author, unresolved=True)
    assert [c.id for c in unresolved.comments] == [rig.comment.id]
    assert await _thread_changes(db, rig.comment.id) == [{"field": "is_thread", "from": False, "to": True}]
    # Saying it again changes nothing and records nothing.
    await service.update_comment(db, rig.comment.id, CommentUpdate(is_thread=True), rig.author)
    assert len(await _thread_changes(db, rig.comment.id)) == 1
    # It is a thread now: it resolves like one.
    resolved = await service.set_resolved(db, rig.comment.id, rig.author, resolved=True)
    assert resolved.resolved_at is not None and not await threads.has_unresolved_threads(db, rig.item.id)


async def test_a_reply_can_never_become_a_thread(db, rig):
    reply = await threads.create_reply(db, rig.comment.id, CommentReplyCreate(body="Yes"), rig.author)
    with pytest.raises(ConflictError, match="A reply cannot become a thread"):
        await service.update_comment(db, reply.id, CommentUpdate(is_thread=True), rig.author)
    assert (await db.get(Comment, reply.id)).is_thread is False


async def test_converting_back_needs_an_unresolved_thread_nobody_answered(db, rig):
    await service.update_comment(db, rig.comment.id, CommentUpdate(is_thread=True), rig.author)
    back = await service.update_comment(db, rig.comment.id, CommentUpdate(is_thread=False), rig.author)
    assert back.is_thread is False and not back.can_resolve
    assert await _thread_changes(db, rig.comment.id) == [
        {"field": "is_thread", "from": False, "to": True}, {"field": "is_thread", "from": True, "to": False},
    ]
    await service.update_comment(db, rig.comment.id, CommentUpdate(is_thread=True), rig.author)
    # Answered: it stays a thread…
    reply = await threads.create_reply(db, rig.comment.id, CommentReplyCreate(body="An answer"), rig.admin)
    with pytest.raises(ConflictError, match="A thread with 1 reply stays a thread"):
        await service.update_comment(db, rig.comment.id, CommentUpdate(is_thread=False), rig.author)
    await service.delete_comment(db, reply.id, rig.admin)
    # …resolved: it stays a thread until reopened…
    await service.set_resolved(db, rig.comment.id, rig.author, resolved=True)
    with pytest.raises(ConflictError, match="A resolved thread stays a thread"):
        await service.update_comment(db, rig.comment.id, CommentUpdate(is_thread=False), rig.author)
    await service.set_resolved(db, rig.comment.id, rig.author, resolved=False)
    assert (await service.update_comment(db, rig.comment.id, CommentUpdate(is_thread=False), rig.author)).is_thread is False
    # …and an inline annotation is a thread by nature.
    space = await spaces.create_space(db, PageSpaceCreate(name="Conversion", slug=f"conv-{rig.item.id.hex[:8]}"), rig.admin.id)
    page = await pages.create_page(db, PageCreate(space_id=space.id, title="Annotated", body="Selected passage"), rig.admin.id)
    inline = await service.create_comment(
        db, page.id, CommentCreate(body="Here?", anchor=CommentAnchor(quote="Selected passage")), rig.admin, entity_type="page"
    )
    with pytest.raises(ConflictError, match="inline comment is always"):
        await service.update_comment(db, inline.id, CommentUpdate(is_thread=False), rig.admin)


async def test_only_the_author_or_a_manager_starts_a_thread_from_a_comment(db, rig):
    with pytest.raises(ForbiddenError):
        await service.update_comment(db, rig.comment.id, CommentUpdate(is_thread=True), rig.stranger)
    assert (await db.get(Comment, rig.comment.id)).is_thread is False
    converted = await service.update_comment(db, rig.comment.id, CommentUpdate(is_thread=True), rig.admin)
    assert converted.is_thread and converted.author.id == rig.author.id


async def test_update_comment_over_mcp_converts_and_refuses_a_reply(db, rig):
    receipt = await tools.call_tool(db, rig.author, UPDATE_COMMENT.name, {"comment_id": str(rig.comment.id), "is_thread": True})
    assert receipt["is_thread"] is True and receipt["resolved"] is False
    assert await threads.has_unresolved_threads(db, rig.item.id)
    reply = await threads.create_reply(db, rig.comment.id, CommentReplyCreate(body="Yes"), rig.author)
    with pytest.raises(ConflictError, match="A reply cannot become a thread"):
        await tools.call_tool(db, rig.author, UPDATE_COMMENT.name, {"comment_id": str(reply.id), "is_thread": True})
    with pytest.raises(ConflictError, match="stays a thread"):
        await tools.call_tool(db, rig.author, UPDATE_COMMENT.name, {"comment_id": str(rig.comment.id), "is_thread": False})
