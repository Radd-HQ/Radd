"""A reply is edited and deleted like a comment (RADD-1477, GitHub #34): by its
author, or by a project manager, and by nobody else. A thread root that still
has replies is REFUSED with the reason — the conversation is deleted from the
end, never by cutting off its first line. The same over MCP (`update_comment`,
`delete_comment`), through the same service seams. Rolled back, never committed.
"""

from types import SimpleNamespace

import pytest

from _factories import make_project, make_user
from radd.exceptions import ConflictError, ForbiddenError
from radd.modules.auth import roles as auth_roles
from radd.modules.auth.models import GlobalRoleGrant
from radd.modules.auth.types import BuiltinRoleKey, InstanceRole
from radd.modules.comments import service, threads
from radd.modules.comments.mcptools import DELETE_COMMENT, UPDATE_COMMENT
from radd.modules.comments.models import Comment
from radd.modules.comments.schemas import CommentCreate, CommentReplyCreate, CommentUpdate
from radd.modules.comments.types import CommentVisibility
from radd.modules.items import service as items
from radd.modules.items.schemas import ItemCreate
from radd.modules.mcp import tools


@pytest.fixture
async def rig(db):
    """An admin's thread on an item; the author's reply under it; a stranger and a
    manager who are project members by ROLE, not by instance rank."""
    admin = await make_user(db, role=InstanceRole.ADMIN, name="Admin")
    author, stranger, manager = [await make_user(db, name=n) for n in ("Author", "Stranger", "Manager")]
    await auth_roles.ensure_builtin_roles(db)
    project = await make_project(db, "ED", "Edit and delete")
    member = await auth_roles.role_by_key(db, BuiltinRoleKey.MEMBER)
    lead = await auth_roles.role_by_key(db, BuiltinRoleKey.MANAGER)
    db.add_all([
        GlobalRoleGrant(project_id=project.id, user_id=author.id, role_id=member.id),
        GlobalRoleGrant(project_id=project.id, user_id=stranger.id, role_id=member.id),
        GlobalRoleGrant(project_id=project.id, user_id=manager.id, role_id=lead.id),
    ])
    await db.flush()
    item = await items.create_item(db, ItemCreate(project_id=project.id, title="edit rig"), admin)
    root = await service.create_comment(db, item.id, CommentCreate(body="A question", is_thread=True), admin)
    reply = await threads.create_reply(db, root.id, CommentReplyCreate(body="An answer"), author)
    return SimpleNamespace(admin=admin, author=author, stranger=stranger, manager=manager, item=item, root=root, reply=reply)


async def test_the_author_edits_and_deletes_their_own_reply(db, rig):
    edited = await service.update_comment(db, rig.reply.id, CommentUpdate(body="A better answer"), rig.author)
    assert edited.body == "A better answer"
    # Editing keeps it a reply, in its thread, at its audience.
    assert edited.parent_comment_id == rig.root.id and edited.visibility is CommentVisibility.PUBLIC
    row = await db.get(Comment, rig.reply.id)
    assert row.parent_comment_id == rig.root.id and row.is_thread is False

    await service.delete_comment(db, rig.reply.id, rig.author)
    await db.flush()
    assert await db.get(Comment, rig.reply.id) is None
    assert await threads.reply_count(db, rig.root.id) == 0
    # The thread itself is untouched by losing its reply.
    root = (await service.list_comments(db, rig.item.id, actor=rig.admin))[0]
    assert root.id == rig.root.id and root.is_thread and root.reply_count == 0


async def test_a_non_author_may_neither_edit_nor_delete_a_reply(db, rig):
    with pytest.raises(ForbiddenError):
        await service.update_comment(db, rig.reply.id, CommentUpdate(body="not mine"), rig.stranger)
    with pytest.raises(ForbiddenError):
        await service.delete_comment(db, rig.reply.id, rig.stranger)
    assert (await db.get(Comment, rig.reply.id)).body == "An answer"


async def test_a_project_manager_edits_and_deletes_another_persons_reply(db, rig):
    edited = await service.update_comment(db, rig.reply.id, CommentUpdate(body="Corrected by the lead"), rig.manager)
    assert edited.body == "Corrected by the lead" and edited.author.id == rig.author.id  # authorship stays
    await service.delete_comment(db, rig.reply.id, rig.manager)
    await db.flush()
    assert await db.get(Comment, rig.reply.id) is None


async def test_a_root_with_replies_is_refused_until_its_replies_are_gone(db, rig):
    with pytest.raises(ConflictError, match="1 reply; delete them first"):
        await service.delete_comment(db, rig.root.id, rig.admin)
    assert await db.get(Comment, rig.root.id) is not None
    await service.delete_comment(db, rig.reply.id, rig.author)
    await service.delete_comment(db, rig.root.id, rig.admin)
    await db.flush()
    assert await db.get(Comment, rig.root.id) is None


async def test_a_stranger_gets_the_permission_refusal_not_the_reply_count(db, rig):
    """The gate runs before the count: a 403, never a 409 that says how big the thread is."""
    with pytest.raises(ForbiddenError):
        await service.delete_comment(db, rig.root.id, rig.stranger)


async def test_a_patch_without_a_body_leaves_the_text_alone(db, rig):
    edited = await service.update_comment(db, rig.reply.id, CommentUpdate(visible_to_teams=[]), rig.author)
    assert edited.body == "An answer"


async def test_update_and_delete_comment_over_mcp_for_a_comment_and_a_reply(db, rig):
    plain = await service.create_comment(db, rig.item.id, CommentCreate(body="A plain comment"), rig.author)

    for target in (rig.reply, plain):
        receipt = await tools.call_tool(db, rig.author, UPDATE_COMMENT.name, {"comment_id": str(target.id), "body": "Edited over MCP"})
        assert receipt["id"] == str(target.id) and receipt["is_thread"] is False and "body" not in receipt
        assert (await db.get(Comment, target.id)).body == "Edited over MCP"
    # A reply's receipt names its thread; a comment's does not.
    assert (await tools.call_tool(db, rig.author, UPDATE_COMMENT.name, {"comment_id": str(rig.reply.id)}))["parent_comment_id"] == str(rig.root.id)

    with pytest.raises(ForbiddenError):
        await tools.call_tool(db, rig.stranger, UPDATE_COMMENT.name, {"comment_id": str(rig.reply.id), "body": "not mine"})
    with pytest.raises(ForbiddenError):
        await tools.call_tool(db, rig.stranger, DELETE_COMMENT.name, {"comment_id": str(plain.id)})
    with pytest.raises(ConflictError, match="delete them first"):
        await tools.call_tool(db, rig.admin, DELETE_COMMENT.name, {"comment_id": str(rig.root.id)})

    for target, actor in ((rig.reply, rig.author), (plain, rig.manager)):
        assert await tools.call_tool(db, actor, DELETE_COMMENT.name, {"comment_id": str(target.id)}) == {"id": str(target.id), "deleted": True}
    await db.flush()
    assert await db.get(Comment, rig.reply.id) is None and await db.get(Comment, plain.id) is None
