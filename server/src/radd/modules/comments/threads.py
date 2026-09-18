"""Flat replies under any comment (RADD-1226 for annotations, RADD-1246 for
every surface), each with an audience of its own bounded by its thread's.

The rule, in one place (`reply_audience`):

- an INTERNAL thread makes every reply internal — a public reply is refused —
  and a reply's teams may only NARROW the thread's (no teams sent = inherit);
- a PUBLIC thread takes public replies and internal ones alike, the internal
  ones to any teams the writer may address (`_check_internal` still gates the
  atom).

Replies are one level deep: a reply to a reply is refused, as before.
"""
import uuid

from fastapi import HTTPException
from sqlalchemy import select, tuple_

from radd.exceptions import ConflictError, NotFoundError
from .models import Comment
from .parents import binding_for
from .reading import _boundary, _cursor, _hydrate, _read_query, audience
from .schemas import CommentCreate, CommentPage
from .types import CommentEntity, CommentSlice, CommentVisibility


def reply_audience(
    root: Comment,
    root_teams: set[uuid.UUID],
    visibility: CommentVisibility | None,
    teams: list[uuid.UUID] | set[uuid.UUID],
) -> tuple[CommentVisibility, set[uuid.UUID]]:
    """A reply's (visibility, teams), given what was asked and what the thread
    allows. Raises ConflictError when the ask reaches past the thread."""
    wanted = set(teams)
    if CommentVisibility(root.visibility) is CommentVisibility.INTERNAL:
        if visibility is not None and visibility is not CommentVisibility.INTERNAL:
            raise ConflictError(CommentEntity.COMMENT, reason="Replies to an internal thread are internal")
        if not wanted:
            return CommentVisibility.INTERNAL, set(root_teams)
        if root_teams and not wanted <= root_teams:
            raise ConflictError(
                CommentEntity.COMMENT, reason="A reply cannot reach teams its thread does not"
            )
        return CommentVisibility.INTERNAL, wanted
    resolved = visibility or CommentVisibility.PUBLIC
    return resolved, (wanted if resolved is CommentVisibility.INTERNAL else set())


async def require_thread(session, comment_id, actor, *, lock=False):
    query = select(Comment).where(Comment.id == comment_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    root = await session.scalar(query)
    if root is None:
        raise NotFoundError(CommentEntity.COMMENT, comment_id)
    query = await _read_query(session, root.entity_id, actor, root.entity_type, CommentSlice.ALL)
    if root.parent_comment_id or await session.scalar(query.where(Comment.id == root.id)) is None:
        raise NotFoundError(CommentEntity.COMMENT, comment_id)
    return root


async def reply_page(session, comment_id, actor, *, limit=50, before=None):
    root = await require_thread(session, comment_id, actor)
    if not 1 <= limit <= 200:
        raise HTTPException(422, "Comment page limit must be between 1 and 200")
    # The reader's own audience filters the replies: an internal reply under a
    # public thread is invisible to whoever may not read internal comments.
    allowed = await audience(session, root.entity_id, actor, root.entity_type)
    query = select(Comment).where(Comment.parent_comment_id == comment_id)
    if allowed is not None:
        query = query.where(allowed)
    if before:
        query = query.where(tuple_(Comment.created_at, Comment.id) < tuple_(*_boundary(before)))
    rows = list((await session.scalars(query.order_by(Comment.created_at.desc(), Comment.id.desc()).limit(limit + 1))).all())
    more = len(rows) > limit
    rows = rows[:limit]
    return CommentPage(comments=await _hydrate(session, list(reversed(rows)), allowed),
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
    root_teams = (await _team_restrictions(session, [root.id])).get(root.id, set())
    visibility, teams = reply_audience(root, root_teams, data.visibility, data.visible_to_teams)
    return await create_authorized_comment(session, root.entity_id,
        CommentCreate(body=data.body, visibility=visibility, visible_to_teams=sorted(teams)),
        actor, entity_type=root.entity_type, permissions=permissions, parent_comment_id=root.id)


async def narrow_replies(session, root: Comment, root_teams: set[uuid.UUID]) -> None:
    """A thread's audience is its replies' ceiling: when an internal root is
    narrowed to `root_teams`, every reply that reached wider is pulled in."""
    from .service import _set_teams, _team_restrictions

    if not root_teams:
        return
    replies = list((await session.scalars(select(Comment).where(Comment.parent_comment_id == root.id))).all())
    restrictions = await _team_restrictions(session, [reply.id for reply in replies])
    for reply in replies:
        current = restrictions.get(reply.id, set())
        if not current or not current <= root_teams:
            await _set_teams(session, reply, sorted(current & root_teams or root_teams))
