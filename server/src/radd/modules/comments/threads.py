"""Flat replies inherit their anchored root's live audience and parent gates."""
from fastapi import HTTPException
from sqlalchemy import select, tuple_

from radd.exceptions import ConflictError, NotFoundError
from .models import Comment
from .parents import binding_for
from .reading import _boundary, _cursor, _hydrate, _read_query
from .schemas import CommentCreate, CommentPage
from .types import CommentEntity, CommentSlice, CommentVisibility


async def require_thread(session, comment_id, actor, *, lock=False):
    query = select(Comment).where(Comment.id == comment_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    root = await session.scalar(query)
    if root is None:
        raise NotFoundError(CommentEntity.COMMENT, comment_id)
    query = await _read_query(session, root.entity_id, actor, root.entity_type, CommentSlice.INLINE)
    if root.parent_comment_id or not root.anchor or await session.scalar(query.where(Comment.id == root.id)) is None:
        raise NotFoundError(CommentEntity.COMMENT, comment_id)
    return root


async def reply_page(session, comment_id, actor, *, limit=50, before=None):
    root = await require_thread(session, comment_id, actor)
    if not 1 <= limit <= 200:
        raise HTTPException(422, "Comment page limit must be between 1 and 200")
    query = select(Comment).where(Comment.parent_comment_id == comment_id)
    if before:
        query = query.where(tuple_(Comment.created_at, Comment.id) < tuple_(*_boundary(before)))
    rows = list((await session.scalars(query.order_by(Comment.created_at.desc(), Comment.id.desc()).limit(limit + 1))).all())
    more = len(rows) > limit
    rows = rows[:limit]
    from .service import _team_restrictions
    audience = sorted((await _team_restrictions(session, [root.id])).get(root.id, set()))
    replies = [reply.model_copy(update={"visibility": CommentVisibility(root.visibility), "visible_to_teams": audience})
               for reply in await _hydrate(session, list(reversed(rows)))]
    return CommentPage(comments=replies,
                       older_cursor=_cursor(rows[-1]) if more else None)


async def create_reply(session, comment_id, data, actor):
    from .service import _team_restrictions, create_authorized_comment

    root = await require_thread(session, comment_id, actor, lock=True)
    binding = binding_for(root.entity_type)
    project = await binding.project_of(session, root.entity_id)
    permissions = await binding.require_write(session, actor, root.entity_id, project)
    if root.resolved_at:
        raise ConflictError(CommentEntity.COMMENT, reason="Reopen this thread before replying")
    if not data.body.strip():
        raise HTTPException(422, "Reply must not be blank")
    audience = (await _team_restrictions(session, [root.id])).get(root.id, set())
    return await create_authorized_comment(session, root.entity_id,
        CommentCreate(body=data.body, visibility=CommentVisibility(root.visibility), visible_to_teams=list(audience)),
        actor, entity_type=root.entity_type, permissions=permissions, parent_comment_id=root.id)
