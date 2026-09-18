import uuid
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, ForbiddenError, NotFoundError
from radd.modules.auth import authz, service as auth
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.kernel import changes
from radd.modules.events import service as events
from radd.modules.items.schemas import UserRef
from radd.modules.teams import service as teams
from radd.modules.projects.models import Project

from .models import Comment, CommentVisibilityTeam
from .parents import binding_for
from .schemas import CommentAnchor, CommentCreate, CommentRead, CommentUpdate
from .types import (
    EXCERPT_MAX_CHARS,
    CommentEntity,
    CommentEvent,
    CommentParentType,
    CommentVisibility,
)
from .reading import comment_page as comment_page, list_comments as list_comments
from radd.clock import utcnow


def _to_read(
    comment: Comment, author: User | None, visible_to_teams: set[uuid.UUID] | None = None
) -> CommentRead:
    return CommentRead(
        id=comment.id,
        entity_type=comment.entity_type,
        entity_id=comment.entity_id,
        author=UserRef(
            id=author.id,
            name=author.name,
            avatar_color=author.avatar_color,
            avatar_emoji=author.avatar_emoji,
        ) if author else None,
        body=comment.body,
        visibility=CommentVisibility(comment.visibility),
        visible_to_teams=sorted(visible_to_teams or set()),
        created_at=comment.created_at,
        updated_at=comment.updated_at,
        anchor=CommentAnchor(**comment.anchor) if comment.anchor else None,
        resolved_at=comment.resolved_at,
        resolved_by=comment.resolved_by,
        parent_comment_id=comment.parent_comment_id,
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


async def comment_audiences(
    session: AsyncSession, comment_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict]:
    """Body-free audience metadata for an operator's import-provenance audit.

    Internal service seam, not an HTTP reader. The caller owns authorization.
    """
    rows = await session.execute(
        select(Comment.id, Comment.entity_type, Comment.entity_id, Comment.visibility)
        .where(Comment.id.in_(comment_ids))
    )
    restrictions = await _team_restrictions(session, comment_ids)
    return {
        row.id: {
            "entity_type": row.entity_type,
            "entity_id": str(row.entity_id),
            "visibility": row.visibility,
            "team_ids": sorted(str(team) for team in restrictions.get(row.id, set())),
        }
        for row in rows
    }


async def _set_teams(
    session: AsyncSession, comment: Comment, team_ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    """Replace an internal comment's team allow-list (validated to existing teams).
    Public comments never carry restrictions. Returns the stored set."""
    wanted = set(team_ids) if comment.visibility == CommentVisibility.INTERNAL.value else set()
    valid = await teams.existing_ids(session, wanted)
    missing = wanted - valid
    if missing:
        raise ConflictError(CommentEntity.COMMENT, reason=f"team {min(missing)} does not exist")
    # Validate before replacing the old audience, even if a caller catches refusal.
    await session.execute(
        delete(CommentVisibilityTeam).where(CommentVisibilityTeam.comment_id == comment.id)
    )
    session.add_all([CommentVisibilityTeam(comment_id=comment.id, team_id=team_id) for team_id in wanted])
    await session.flush()
    return wanted


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


async def public_comments_for_item(
    session: AsyncSession, item_id: uuid.UUID
) -> list[Comment]:
    """PUBLIC comment rows on one item, oldest first — the requester-portal
    thread (forms.requests.get_request, RADD-887). A requester may read exactly
    the public conversation, never the internal one, and the visibility filter
    lives HERE in the query — the RADD-785 rule — so no caller can compose a
    view that leaks an internal note."""
    result = await session.execute(
        select(Comment)
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
) -> list[tuple[uuid.UUID, uuid.UUID | None, datetime]]:
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


async def public_reply_body(
    session: AsyncSession, comment_id: uuid.UUID, item_id: uuid.UUID
) -> str | None:
    """Current public body for external mail; a stale event cannot disclose a
    comment that has since been made internal, deleted or moved."""
    return await session.scalar(select(Comment.body).where(
        Comment.id == comment_id,
        Comment.entity_type == CommentParentType.ITEM.value,
        Comment.entity_id == item_id,
        Comment.visibility == CommentVisibility.PUBLIC.value,
    ))


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
    """EDITS: authors act on their own comments (comment.write); others need
    `others` (spec 50: project.manage). DELETES (RADD-816/Q4) are relation-
    aware instead: the author-own right is the Baseline's `comment.delete@own`
    grant — explainable in the inspector and revocable, which the hardcoded
    author check never was."""
    if others is Permission.COMMENT_DELETE:
        permissions = await authz.require(session, actor, Permission.COMMENT_DELETE, project=project)
        relations = authz.relations_held(permissions, Permission.COMMENT_DELETE)
        if authz.RELATION_ANY not in relations:
            relation_actor = await authz.relation_actor(session, actor)
            if not authz.relation_holds_row("comment", relations, relation_actor, comment):
                raise ForbiddenError("you may only delete your own comments here")
        return permissions
    permission = Permission.COMMENT_WRITE if comment.author_id == actor.id else others
    return await authz.require(session, actor, permission, project=project)


async def _emit(
    session: AsyncSession,
    event_type: CommentEvent,
    comment: Comment,
    actor_id: uuid.UUID | None,
    occurred_at: datetime | None = None,
    visible_to_teams: set[uuid.UUID] | None = None,
    diff: list[dict] | None = None,
) -> None:
    # The excerpt is included even for internal comments — in-process consumers
    # are trusted; REST reads filter by visibility, and the webhook egress
    # withholds internal excerpts (RADD-1085: an endpoint sits in no team).
    # `visible_to_teams` (spec 50) lets notify narrow internal fan-out to team members.
    await events.emit(
        session,
        event_type=event_type,
        entity_type=CommentEntity.COMMENT,
        entity_id=comment.id,
        actor_id=actor_id,
        subjects={
            # The kernel resolves it; None when the parent is a page, not an item.
            "item": (
                comment.entity_id if comment.entity_type == CommentParentType.ITEM else None
            )
        },
        payload={
            # The polymorphic parent, which may be a page rather than an item.
            "entity_type": comment.entity_type,
            "entity_id": str(comment.entity_id),
            # The canonical item ref (RADD-922), None when the parent is not an
            # item. It replaces the bare `item_id` that every consumer then had
            # to resolve into a key and a project of its own accord.
            # A REF, not a bare id: a notification that says "3f2a-…" wrote a
            # comment is a notification nobody can read.
            "author": await auth.user_ref_by_id(session, comment.author_id),
            "visibility": comment.visibility,
            "excerpt": comment.body[:EXCERPT_MAX_CHARS],
            "visible_to_teams": sorted(str(team_id) for team_id in (visible_to_teams or set())),
        },
        occurred_at=occurred_at,
        changes=diff,
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
    return await create_authorized_comment(
        session, entity_id, data, actor, entity_type=entity_type, permissions=permissions
    )


async def create_authorized_comment(
    session: AsyncSession,
    entity_id: uuid.UUID,
    data: CommentCreate,
    actor: User,
    *,
    entity_type: str = CommentParentType.ITEM.value,
    permissions: frozenset[Permission] = frozenset(),
    parent_comment_id: uuid.UUID | None = None,
) -> CommentRead:
    """Write a comment whose authorisation the CALLER has already decided.

    `create_comment` is the ordinary door and asks the parent binding. This one
    exists for a caller that authorises by a different rule entirely: the
    requester portal admits by RELATIONSHIP (you reported it, or it was filed for
    your team — RADD-796), and a requester holds `comment.write` nowhere. The
    submit path already extends exactly that trust to create the item.

    It is a separate, named function rather than a `bypass_authz=True` flag on
    the one above, because a boolean that skips permission checks is the kind of
    parameter that gets copied into a caller which had no business skipping
    anything. Passing an EMPTY permission set is deliberate too: an unprivileged
    caller then cannot reach the import overrides or write an internal comment,
    because both are gated on what is in that set.

    Everything downstream is shared — one write path, so events, mentions,
    notifications and watchers behave identically however the comment arrived.
    """
    _check_internal(permissions, data.visibility)
    # Import overrides (author/timestamp) are honored only for a project manager.
    can_import = Permission.PROJECT_MANAGE in permissions
    # An IMPORT states the author explicitly; falling back to the actor there
    # credited whoever ran the import with thousands of other people's comments
    # (spec 90 follow-up). A mapped source user resolves to a real account;
    # skipped or absent source identities remain NULL (RADD-1195).
    author_id = data.author_id if (can_import and "author_id" in data.model_fields_set) else actor.id
    occurred_at = data.created_at if (can_import and data.created_at) else None
    comment = Comment(
        entity_type=entity_type,
        entity_id=entity_id,
        author_id=author_id,
        body=data.body,
        anchor=data.anchor.model_dump() if data.anchor else None,
        visibility=data.visibility.value,
        parent_comment_id=parent_comment_id,
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
    return _to_read(comment, await auth.get_user(session, author_id) if author_id else None, stored_teams)


async def update_comment(
    session: AsyncSession, comment_id: uuid.UUID, data: CommentUpdate, actor: User
) -> CommentRead:
    comment = await _get(session, comment_id)
    if comment.parent_comment_id:
        from .threads import require_thread
        await require_thread(session, comment.parent_comment_id, actor)
        if data.visible_to_teams is not None:
            raise ConflictError(CommentEntity.COMMENT, reason="Replies inherit their thread's audience")
    binding, project = await _parent_scope(session, comment.entity_type, comment.entity_id)
    permissions = await _require_author_or(
        session, comment, actor, project, others=Permission.PROJECT_MANAGE
    )
    _check_internal(permissions, comment.visibility)
    body_changed = comment.body != data.body
    previous_teams = (await _team_restrictions(session, [comment.id])).get(comment.id, set())
    comment.body = data.body
    await session.flush()
    if data.visible_to_teams is not None:
        stored_teams = await _set_teams(session, comment, data.visible_to_teams)
    else:
        stored_teams = previous_teams
    # Spec 123: the body records only that it changed; team visibility by name.
    diff: list[dict] = [changes.hidden_change("body")] if body_changed else []
    if stored_teams != previous_teams:
        names = await teams.teams_by_ids(session, list(previous_teams | stored_teams))
        entry = changes.collection_change(
            "visible_to_teams",
            [names[t].name if t in names else str(t) for t in previous_teams],
            [names[t].name if t in names else str(t) for t in stored_teams],
        )
        if entry is not None:
            diff.append(entry)
    await _emit(
        session, CommentEvent.UPDATED, comment, actor.id,
        visible_to_teams=stored_teams, diff=diff,
    )
    return _to_read(comment, await auth.get_user(session, comment.author_id) if comment.author_id else None, stored_teams)


async def delete_comment(session: AsyncSession, comment_id: uuid.UUID, actor: User) -> None:
    comment = await _get(session, comment_id)
    if comment.parent_comment_id:
        from .threads import require_thread
        await require_thread(session, comment.parent_comment_id, actor)
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


async def set_resolved(
    session: AsyncSession, comment_id: uuid.UUID, actor: User, *, resolved: bool
) -> CommentRead:
    """Resolve or reopen an inline comment (RADD-726/729).

    Same authorization as EDITING it — resolving is a statement about the
    conversation, not a destructive act, and anyone who could rewrite the comment
    can certainly close it. Idempotent: resolving a resolved comment is not an
    error, because two people clicking at once is ordinary.
    """
    comment = await _get(session, comment_id)
    if comment.parent_comment_id:
        raise ConflictError(CommentEntity.COMMENT, reason="Resolve the thread, not an individual reply")
    binding, project = await _parent_scope(session, comment.entity_type, comment.entity_id)
    await _require_author_or(
        session, comment, actor, project, others=binding.manage_permission
    )
    was_resolved = comment.resolved_at is not None
    comment.resolved_at = utcnow() if resolved else None
    comment.resolved_by = actor.id if resolved else None
    await session.flush()
    if was_resolved != resolved:  # spec 123: resolving is an update to the record
        stored_teams = (await _team_restrictions(session, [comment.id])).get(comment.id, set())
        await _emit(
            session, CommentEvent.UPDATED, comment, actor.id,
            visible_to_teams=stored_teams,
            diff=[{"field": "resolved", "from": was_resolved, "to": resolved}],
        )
    author = await auth.get_user(session, comment.author_id) if comment.author_id else None
    return _to_read(comment, author)
