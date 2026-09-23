"""Permission-filtered discussion reads and stable keyset pagination."""

import base64
import binascii
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import JSON, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.modules.auth import service as auth
from radd.modules.teams import service as teams

from .models import Comment, CommentVisibilityTeam
from .parents import binding_for
from radd.exceptions import ForbiddenError, NotFoundError, UnauthorizedError

from .schemas import CommentLocation, CommentPage, CommentRead
from .types import CommentParentType, CommentSlice, CommentVisibility


_EVERYTHING = object()  # sentinel: "compute the audience here"

#: RADD-1297: how far back a `through` window may reach to include a linked
#: comment. Past this the link lands on the thread without the comment in view.
THROUGH_MAX = 1000


async def audience(session, entity_id, actor, entity_type):
    """The rows of this parent the actor may read, as a WHERE clause — or None
    when they may read every row (project.manage). RADD-1246: one clause for
    roots AND replies, so a reply carries its own audience instead of
    borrowing its root's."""
    binding = binding_for(entity_type)
    project = await binding.project_of(session, entity_id)
    permissions = await binding.require_read(session, actor, entity_id, project)
    if Permission.PROJECT_MANAGE in permissions:
        return None
    allowed = [Comment.visibility != CommentVisibility.INTERNAL, Comment.author_id == actor.id]
    if Permission.COMMENT_READ_INTERNAL in permissions:
        actor_teams = await teams.user_team_ids(session, actor.id)
        restrictions = select(CommentVisibilityTeam.comment_id).where(
            CommentVisibilityTeam.comment_id == Comment.id
        )
        allowed.append(~restrictions.exists())
        allowed.append(restrictions.where(CommentVisibilityTeam.team_id.in_(actor_teams)).exists())
    return or_(*allowed)


async def _read_query(session, entity_id, actor, entity_type, section, allowed=_EVERYTHING, *, unresolved=False):
    if allowed is _EVERYTHING:
        allowed = await audience(session, entity_id, actor, entity_type)
    query = select(Comment).where(Comment.entity_type == entity_type, Comment.entity_id == entity_id,
                                  Comment.parent_comment_id.is_(None))
    # RADD-1283: a filter, not a section — it composes with `discussion` (a page's
    # Discussion) as well as `all` (an issue), without pulling annotations in.
    if unresolved:
        query = query.where(Comment.is_thread.is_(True), Comment.resolved_at.is_(None))
    if allowed is not None:
        query = query.where(allowed)
    # Historical JSONB nulls and SQL NULL both represent an ordinary discussion.
    if section is CommentSlice.INLINE:
        query = query.where(Comment.anchor.is_not(None), Comment.anchor != JSON.NULL)
    elif section is CommentSlice.DISCUSSION:
        query = query.where(or_(Comment.anchor.is_(None), Comment.anchor == JSON.NULL))
    return query


async def _hydrate(session, rows, allowed=None, actor=None, entity=None):
    """Reads for `rows`; `reply_count` counts the replies THIS actor may read
    (`allowed` is the audience clause), on every root — RADD-1246 made every
    comment a thread root, not only anchored ones."""
    from .service import _team_restrictions, _to_read

    restrictions = await _team_restrictions(session, [row.id for row in rows])
    people = {row.author_id for row in rows if row.author_id is not None}
    people |= {row.resolved_by for row in rows if row.resolved_by is not None}
    authors = await auth.users_by_ids(session, people)
    roots = [row.id for row in rows if row.parent_comment_id is None]
    counting = select(Comment.parent_comment_id, func.count()).where(Comment.parent_comment_id.in_(roots))
    if allowed is not None:
        counting = counting.where(allowed)
    counts = dict((await session.execute(counting.group_by(Comment.parent_comment_id))).all()) if roots else {}
    # RADD-1283: the reader's reach under the parent's rule, once per parent.
    reach = None
    if actor is not None and entity is not None and any(row.is_thread for row in rows):
        from .resolution import resolve_reach

        reach = await resolve_reach(session, actor, *entity)
    return [_to_read(row, authors.get(row.author_id), restrictions.get(row.id),
                     authors.get(row.resolved_by) if row.resolved_by else None)
            .model_copy(update={"reply_count": counts.get(row.id, 0),
                                "can_resolve": reach is not None and _covers(reach, row, actor)})
            for row in rows]


def _covers(reach, row, actor) -> bool:
    from .resolution import reach_covers

    return reach_covers(reach, row, actor)


def _cursor(row: Comment) -> str:
    return base64.urlsafe_b64encode(f"{row.created_at.isoformat()}|{row.id}".encode()).decode()


def _boundary(cursor: str):
    try:
        raw = base64.b64decode(cursor, altchars=b'-_', validate=True).decode()
        timestamp, identifier = raw.split('|')
        when = datetime.fromisoformat(timestamp)
        if when.tzinfo is not None:
            when = when.astimezone(UTC).replace(tzinfo=None)
        return when, uuid.UUID(identifier)
    except (ValueError, UnicodeError, binascii.Error) as error:
        raise HTTPException(422, "Invalid comment cursor") from error


async def list_comments(
    session: AsyncSession, entity_id: uuid.UUID, actor: User,
    entity_type: str = CommentParentType.ITEM.value,
) -> list[CommentRead]:
    """Legacy complete-list API; shares the same parent and visibility gates."""
    allowed = await audience(session, entity_id, actor, entity_type)
    query = await _read_query(session, entity_id, actor, entity_type, CommentSlice.ALL, allowed)
    rows = list((await session.scalars(query.order_by(Comment.created_at, Comment.id))).all())
    return await _hydrate(session, rows, allowed, actor, (entity_type, entity_id))


async def comment_page(
    session: AsyncSession, entity_id: uuid.UUID, actor: User,
    entity_type: str = CommentParentType.ITEM.value, *, limit: int = 50,
    before: str | None = None, section: CommentSlice = CommentSlice.ALL, unresolved: bool = False,
    through: uuid.UUID | None = None,
) -> CommentPage:
    """Newest window in chronological order; older pages use an exclusive cursor.

    Visibility is filtered in SQL before LIMIT. New comments and deletion of the
    boundary row cannot shift an older page or expose hidden rows in its cursor.
    """
    if not 1 <= limit <= 200:
        raise HTTPException(422, "Comment page limit must be between 1 and 200")
    allowed = await audience(session, entity_id, actor, entity_type)
    query = await _read_query(session, entity_id, actor, entity_type, section, allowed, unresolved=unresolved)
    if before:
        query = query.where(tuple_(Comment.created_at, Comment.id) < tuple_(*_boundary(before)))
    elif through is not None:
        # RADD-1297: a link to one comment — widen the NEWEST window just far
        # enough to include it, however old it is. Counted on the same
        # audience-filtered query, so the widening itself reveals nothing.
        target = await session.get(Comment, through)
        if target is not None and target.entity_id == entity_id and target.entity_type == entity_type:
            newer = await session.scalar(
                select(func.count()).select_from(
                    query.where(
                        tuple_(Comment.created_at, Comment.id) >= tuple_(target.created_at, target.id)
                    ).subquery()
                )
            )
            limit = max(limit, min(newer or 0, THROUGH_MAX))
    query = query.order_by(Comment.created_at.desc(), Comment.id.desc()).limit(limit + 1)
    rows = list((await session.scalars(query)).all())
    more = len(rows) > limit
    rows = rows[:limit]
    return CommentPage(
        comments=await _hydrate(session, list(reversed(rows)), allowed, actor, (entity_type, entity_id)),
        older_cursor=_cursor(rows[-1]) if more else None,
    )


async def locate(session: AsyncSession, comment_id: uuid.UUID, actor: User) -> CommentLocation:
    """RADD-1297: where a linked comment lives — its thread root, parent, and
    whether it is an inline annotation. A comment the reader cannot see is
    NOT FOUND, exactly like one that does not exist."""
    comment = await session.get(Comment, comment_id)
    try:
        readable = comment is not None and await can_read_comment(session, comment_id, actor)
    except (NotFoundError, ForbiddenError, UnauthorizedError, HTTPException):
        # The parent's own refusal (a restricted issue, a private page) is a
        # "no" too — and answered the same way as a comment that never existed.
        readable = False
    if not readable:
        raise NotFoundError("comment", comment_id)
    root = await session.get(Comment, comment.parent_comment_id) if comment.parent_comment_id else comment
    return CommentLocation(
        id=comment.id,
        root_id=root.id,
        entity_type=root.entity_type,
        entity_id=root.entity_id,
        anchored=root.anchor is not None,
    )


async def can_read_comment(session, comment_id, actor):
    """Live parent and discussion visibility for deferred delivery."""
    comment = await session.get(Comment, comment_id)
    if comment is None:
        return False
    reply = None
    if comment.parent_comment_id:
        reply, comment = comment, await session.get(Comment, comment.parent_comment_id)
        if comment is None:
            return False
    allowed = await audience(session, comment.entity_id, actor, comment.entity_type)
    query = await _read_query(session, comment.entity_id, actor, comment.entity_type, CommentSlice.ALL, allowed)
    if await session.scalar(query.where(Comment.id == comment.id)) is None:
        return False
    if reply is None or allowed is None:
        return True
    # RADD-1246: a reply has an audience of its own (an internal reply under a
    # public thread) — the root being readable is necessary, not sufficient.
    return await session.scalar(select(Comment.id).where(Comment.id == reply.id, allowed)) is not None
