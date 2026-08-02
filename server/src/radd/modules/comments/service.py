import uuid
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, ForbiddenError, NotFoundError
from radd.modules.auth import authz, service as auth
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.modules.events import service as events
from radd.modules.items import service as items
from radd.modules.items.schemas import UserRef
from radd.modules.teams import service as teams
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project

from .models import Comment, CommentVisibilityTeam
from .parents import binding_for
from .schemas import CommentCreate, CommentRead, CommentUpdate
from .types import (
    EXCERPT_MAX_CHARS,
    CommentEntity,
    CommentEvent,
    CommentParentType,
    CommentVisibility,
)
from .visibility import internal_comment_visible


def _to_read(
    comment: Comment, author: User, visible_to_teams: set[uuid.UUID] | None = None
) -> CommentRead:
    return CommentRead(
        id=comment.id,
        entity_type=comment.entity_type,
        entity_id=comment.entity_id,
        # Kept so every existing issue-side caller is untouched: it is the
        # entity id when the parent IS an item, and null otherwise.
        item_id=comment.entity_id if comment.entity_type == CommentParentType.ITEM else None,
        author=UserRef(
            id=author.id,
            name=author.name,
            avatar_color=author.avatar_color,
            avatar_emoji=author.avatar_emoji,
        ),
        body=comment.body,
        visibility=CommentVisibility(comment.visibility),
        visible_to_teams=sorted(visible_to_teams or set()),
        created_at=comment.created_at,
        updated_at=comment.updated_at,
    )


async def _team_restrictions(
    session: AsyncSession, comment_ids: list[uuid.UUID]
) -> dict[uuid.UUID, set[uuid.UUID]]:
    """{comment_id -> {team_id}} for the given comments (spec 50 — empty = unrestricted)."""
    if not comment_ids:
        return {}
    rows = await session.execute(
        select(CommentVisibilityTeam.comment_id, CommentVisibilityTeam.team_id).where(
            CommentVisibilityTeam.comment_id.in_(comment_ids)
        )
    )
    out: dict[uuid.UUID, set[uuid.UUID]] = {}
    for comment_id, team_id in rows.all():
        out.setdefault(comment_id, set()).add(team_id)
    return out


async def _set_teams(
    session: AsyncSession, comment: Comment, team_ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    """Replace an internal comment's team allow-list (validated to existing teams).
    Public comments never carry restrictions. Returns the stored set."""
    await session.execute(
        delete(CommentVisibilityTeam).where(CommentVisibilityTeam.comment_id == comment.id)
    )
    if comment.visibility != CommentVisibility.INTERNAL.value or not team_ids:
        return set()
    valid = {team.id for team in await teams.list_teams(session)}
    stored: set[uuid.UUID] = set()
    for team_id in team_ids:
        if team_id not in valid:
            raise ConflictError(
                CommentEntity.COMMENT, reason=f"team {team_id} does not exist"
            )
        if team_id not in stored:
            session.add(CommentVisibilityTeam(comment_id=comment.id, team_id=team_id))
            stored.add(team_id)
    await session.flush()
    return stored


async def public_bodies_for_item(session: AsyncSession, item_id: uuid.UUID) -> list[str]:
    """PUBLIC comment bodies, oldest first — the search indexer's aggregation seam.
    Internal bodies are excluded so their text is never findable via plain item.read."""
    result = await session.execute(
        select(Comment.body)
        .where(
            Comment.entity_type == CommentParentType.ITEM,
            Comment.entity_id == item_id,
            Comment.visibility == CommentVisibility.PUBLIC.value,
        )
        .order_by(Comment.created_at)
    )
    return list(result.scalars())


async def public_comment_times(
    session: AsyncSession, item_ids: Iterable[uuid.UUID]
) -> list[tuple[uuid.UUID, uuid.UUID, datetime]]:
    """(item_id, author_id, created_at) for every PUBLIC comment on the items,
    oldest first — the SLA first-response seam (spec 30)."""
    ids = list(item_ids)
    if not ids:
        return []
    result = await session.execute(
        select(Comment.entity_id, Comment.author_id, Comment.created_at)
        .where(
            Comment.entity_type == CommentParentType.ITEM,
            Comment.entity_id.in_(ids),
            Comment.visibility == CommentVisibility.PUBLIC.value,
        )
        .order_by(Comment.created_at)
    )
    return [tuple(row) for row in result.all()]  # type: ignore[misc]


async def comment_body(session: AsyncSession, comment_id: uuid.UUID) -> str | None:
    """Full body for stream consumers (the event excerpt is capped — notify
    mention-scans the whole text). None if the comment is gone."""
    comment = await session.get(Comment, comment_id)
    return comment.body if comment else None


async def _get(session: AsyncSession, comment_id: uuid.UUID) -> Comment:
    comment = await session.get(Comment, comment_id)
    if comment is None:
        raise NotFoundError(CommentEntity.COMMENT, comment_id)
    return comment


async def _parent_scope(
    session: AsyncSession, entity_type: str, entity_id: uuid.UUID
) -> tuple[object, Project | None]:
    """The binding for this parent and the project it lives in, if any.

    None is a legitimate answer, not a failure: a wiki page is global, so the
    permission checks below run at global scope — which is exactly how page
    atoms are granted.
    """
    binding = binding_for(entity_type)
    return binding, await binding.project_of(session, entity_id)


def _check_internal(permissions: frozenset[Permission], visibility: str) -> None:
    """Internal comments are invisible/untouchable without COMMENT_READ_INTERNAL."""
    if (
        CommentVisibility(visibility) is CommentVisibility.INTERNAL
        and Permission.COMMENT_READ_INTERNAL not in permissions
    ):
        raise ForbiddenError(
            f"permission '{Permission.COMMENT_READ_INTERNAL}' required for internal comments"
        )


async def _require_author_or(
    session: AsyncSession,
    comment: Comment,
    actor: User,
    project: Project | None,
    *,
    others: Permission,
) -> frozenset[Permission]:
    """Authors act on their own comments (comment.write); others need `others`
    (spec 50: comment.delete for deletion, project.manage for editing another's)."""
    permission = Permission.COMMENT_WRITE if comment.author_id == actor.id else others
    return await authz.require(session, actor, permission, project=project)


async def _emit(
    session: AsyncSession,
    event_type: CommentEvent,
    comment: Comment,
    actor_id: uuid.UUID,
    occurred_at: datetime | None = None,
    visible_to_teams: set[uuid.UUID] | None = None,
) -> None:
    # The excerpt is included even for internal comments — the event stream/webhooks are
    # trusted consumers (docs/modules.md); only the REST reads filter by visibility.
    # `visible_to_teams` (spec 50) lets notify narrow internal fan-out to team members.
    await events.emit(
        session,
        event_type=event_type,
        entity_type=CommentEntity.COMMENT,
        entity_id=comment.id,
        actor_id=actor_id,
        payload={
            # Both shapes: `item_id` keeps every existing consumer (notify,
            # webhooks, automations, the extensions SDK) working untouched, and
            # is null when the parent is not an item.
            "entity_type": comment.entity_type,
            "entity_id": str(comment.entity_id),
            "item_id": (
                str(comment.entity_id)
                if comment.entity_type == CommentParentType.ITEM
                else None
            ),
            "author_id": str(comment.author_id),
            "visibility": comment.visibility,
            "excerpt": comment.body[:EXCERPT_MAX_CHARS],
            "visible_to_teams": sorted(str(team_id) for team_id in (visible_to_teams or set())),
        },
        occurred_at=occurred_at,
    )


async def create_comment(
    session: AsyncSession,
    entity_id: uuid.UUID,
    data: CommentCreate,
    actor: User,
    entity_type: str = CommentParentType.ITEM.value,
) -> CommentRead:
    binding, project = await _parent_scope(session, entity_type, entity_id)
    permissions = await binding.require_write(session, actor, entity_id, project)
    _check_internal(permissions, data.visibility)
    # Import overrides (author/timestamp) are honored only for a project manager.
    can_import = Permission.PROJECT_MANAGE in permissions
    # An IMPORT states the author explicitly; falling back to the actor there
    # credited whoever ran the import with thousands of other people's comments
    # (spec 90 follow-up). The importer now provisions a placeholder
    # account for anyone unknown, so `author_id` is set — and an import that
    # still cannot name the author leaves it unattributed rather than wrong.
    author_id = data.author_id if (can_import and "author_id" in data.model_fields_set) else actor.id
    occurred_at = data.created_at if (can_import and data.created_at) else None
    comment = Comment(
        entity_type=entity_type,
        entity_id=entity_id,
        author_id=author_id,
        body=data.body,
        visibility=data.visibility.value
    )
    if occurred_at is not None:
        comment.created_at = occurred_at.replace(tzinfo=None)
    session.add(comment)
    await session.flush()
    stored_teams = await _set_teams(session, comment, data.visible_to_teams)
    await _emit(
        session, CommentEvent.CREATED, comment, author_id,
        occurred_at=occurred_at, visible_to_teams=stored_teams,
    )
    return _to_read(comment, actor, stored_teams)


async def _visible_comments(
    session: AsyncSession,
    comments: list[Comment],
    actor: User,
    project: Project,
    permissions: frozenset[Permission],
    restrictions: dict[uuid.UUID, set[uuid.UUID]],
) -> list[Comment]:
    """Drop internal comments the actor may not read (spec 50 — teams narrow the
    read_internal audience). Public comments always pass."""
    internal = [c for c in comments if c.visibility == CommentVisibility.INTERNAL.value]
    if not internal:
        return comments
    has_read = Permission.COMMENT_READ_INTERNAL in permissions
    has_manage = Permission.PROJECT_MANAGE in permissions
    actor_teams = (
        set()
        if has_manage
        else await teams.user_team_ids(session, actor.id)
    )
    return [
        c
        for c in comments
        if c.visibility != CommentVisibility.INTERNAL.value
        or internal_comment_visible(
            is_author=c.author_id == actor.id,
            has_read_internal=has_read,
            has_manage=has_manage,
            comment_teams=restrictions.get(c.id, set()),
            actor_teams=actor_teams,
        )
    ]


async def list_comments(
    session: AsyncSession,
    entity_id: uuid.UUID,
    actor: User,
    entity_type: str = CommentParentType.ITEM.value,
) -> list[CommentRead]:
    binding, project = await _parent_scope(session, entity_type, entity_id)
    permissions = await authz.require(session, actor, Permission.ITEM_READ, project=project)
    query = (
        select(Comment)
        .where(Comment.entity_type == entity_type, Comment.entity_id == entity_id)
        .order_by(Comment.created_at, Comment.id)
    )
    comments = list((await session.execute(query)).scalars())
    restrictions = await _team_restrictions(
        session, [c.id for c in comments if c.visibility == CommentVisibility.INTERNAL.value]
    )
    comments = await _visible_comments(session, comments, actor, project, permissions, restrictions)
    authors = await auth.users_by_ids(session, {c.author_id for c in comments})
    return [_to_read(c, authors[c.author_id], restrictions.get(c.id)) for c in comments]


async def update_comment(
    session: AsyncSession, comment_id: uuid.UUID, data: CommentUpdate, actor: User
) -> CommentRead:
    comment = await _get(session, comment_id)
    binding, project = await _parent_scope(session, comment.entity_type, comment.entity_id)
    permissions = await _require_author_or(
        session, comment, actor, project, others=Permission.PROJECT_MANAGE
    )
    _check_internal(permissions, comment.visibility)
    comment.body = data.body
    await session.flush()
    if data.visible_to_teams is not None:
        stored_teams = await _set_teams(session, comment, data.visible_to_teams)
    else:
        stored_teams = (await _team_restrictions(session, [comment.id])).get(comment.id, set())
    await _emit(
        session, CommentEvent.UPDATED, comment, actor.id,
        visible_to_teams=stored_teams,
    )
    return _to_read(comment, await auth.get_user(session, comment.author_id), stored_teams)


async def delete_comment(session: AsyncSession, comment_id: uuid.UUID, actor: User) -> None:
    comment = await _get(session, comment_id)
    binding, project = await _parent_scope(session, comment.entity_type, comment.entity_id)
    permissions = await _require_author_or(
        session, comment, actor, project, others=Permission.COMMENT_DELETE
    )
    _check_internal(permissions, comment.visibility)
    await _emit(session, CommentEvent.DELETED, comment, actor.id)
    await session.delete(comment)


async def comment_counts(
    session: AsyncSession, item_ids: Iterable[uuid.UUID], *, include_internal: bool = True
) -> dict[uuid.UUID, int]:
    """Grouped counts for batch item hydration (public helper consumed by items).

    `include_internal=False` counts only public comments — items passes the actor's
    per-project COMMENT_READ_INTERNAL outcome through hydration (spec 07).
    """
    ids = set(item_ids)
    if not ids:
        return {}
    query = select(Comment.entity_id, func.count()).where(
        Comment.entity_type == CommentParentType.ITEM, Comment.entity_id.in_(ids)
    )
    if not include_internal:
        query = query.where(Comment.visibility == CommentVisibility.PUBLIC.value)
    rows = await session.execute(query.group_by(Comment.entity_id))
    return dict(rows.all())


async def delete_for_parent(
    session: AsyncSession, entity_type: str, entity_id: uuid.UUID
) -> int:
    """Remove every comment on a parent that is being destroyed (RADD-717).

    The polymorphic column cannot carry a foreign key, so the ON DELETE CASCADE
    the old `item_id` had is gone and each parent's hard-delete path calls this
    instead. Left undone, a deleted item or page leaves comments that nothing
    can reach and nothing can remove.
    """
    result = await session.execute(
        delete(Comment).where(
            Comment.entity_type == entity_type, Comment.entity_id == entity_id
        )
    )
    return result.rowcount or 0
