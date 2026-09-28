import uuid
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd import tasklists
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
    CommentOrigin,
    CommentParentType,
    CommentVisibility,
)
from .reading import comment_page as comment_page, list_comments as list_comments, locate as locate
from .threads import has_unresolved_threads as has_unresolved_threads
from .threads import lock_thread_parent, narrow_replies, reply_audience, reply_count, require_thread
from radd.clock import utcnow


def _to_read(
    comment: Comment, author: User | None, visible_to_teams: set[uuid.UUID] | None = None,
    resolver: User | None = None,
) -> CommentRead:
    return CommentRead(
        id=comment.id,
        entity_type=comment.entity_type,
        entity_id=comment.entity_id,
        author=UserRef.model_validate(author, from_attributes=True) if author else None,
        body=comment.body,
        email_signature=comment.email_signature,
        is_thread=comment.is_thread,
        visibility=CommentVisibility(comment.visibility),
        visible_to_teams=sorted(visible_to_teams or set()),
        created_at=comment.created_at,
        updated_at=comment.updated_at,
        anchor=CommentAnchor(**comment.anchor) if comment.anchor else None,
        resolved_at=comment.resolved_at,
        resolved_by=comment.resolved_by,
        resolver_name=(resolver.name or resolver.email) if resolver and comment.resolved_at else None,
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


#: PUBLIC comments on items. The visibility filter lives in the query (RADD-785),
#: so no caller can compose a view that leaks an internal note.
_PUBLIC_ON_ITEMS = (
    Comment.entity_type == CommentParentType.ITEM.value,
    Comment.visibility == CommentVisibility.PUBLIC.value,
)


async def public_bodies_for_item(session: AsyncSession, item_id: uuid.UUID) -> list[str]:
    """PUBLIC comment bodies, oldest first — the search indexer's aggregation seam.
    Internal bodies are excluded so their text is never findable via plain item.read."""
    result = await session.execute(
        select(Comment.body).where(*_PUBLIC_ON_ITEMS, Comment.entity_id == item_id).order_by(Comment.created_at)
    )
    return list(result.scalars())


async def public_comments_for_item(
    session: AsyncSession, item_id: uuid.UUID
) -> list[Comment]:
    """PUBLIC comment rows on one item, oldest first — the requester-portal
    thread (forms.requests.get_request, RADD-887): exactly the public conversation."""
    result = await session.execute(
        select(Comment).where(*_PUBLIC_ON_ITEMS, Comment.entity_id == item_id).order_by(Comment.created_at)
    )
    return list(result.scalars())


async def public_comment_times(
    session: AsyncSession, item_ids: Iterable[uuid.UUID]
) -> list[tuple[uuid.UUID, uuid.UUID | None, datetime, str | None]]:
    """(item_id, author_id, created_at, origin) for every PUBLIC comment on the
    items, oldest first — the SLA first-response seam (spec 30). `origin`
    (RADD-1318) is what tells a person's answer from inbound mail or an
    automation."""
    ids = list(item_ids)
    if not ids:
        return []
    result = await session.execute(
        select(Comment.entity_id, Comment.author_id, Comment.created_at, Comment.origin)
        .where(*_PUBLIC_ON_ITEMS, Comment.entity_id.in_(ids))
        .order_by(Comment.created_at)
    )
    return [tuple(row) for row in result.all()]  # type: ignore[misc]


async def public_reply_body(
    session: AsyncSession, comment_id: uuid.UUID, item_id: uuid.UUID
) -> str | None:
    """Current public body for external mail; a stale event cannot disclose a
    comment that has since been made internal, deleted or moved."""
    return await session.scalar(
        select(Comment.body).where(*_PUBLIC_ON_ITEMS, Comment.id == comment_id, Comment.entity_id == item_id)
    )


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
    """(binding, owning project); the project is None for a global parent such as a page."""
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
            ),
            # RADD-1248: and the PAGE when the parent is one — a ref with title,
            # path and space, so an automation can condition on the space and a
            # template can name the page, from the payload alone.
            "page": (
                comment.entity_id if comment.entity_type == CommentParentType.PAGE else None
            ),
        },
        payload={
            # The polymorphic parent, which may be a page rather than an item.
            "entity_type": comment.entity_type,
            "entity_id": str(comment.entity_id),
            # RADD-1248: null for a thread root — the one fact that tells a reply from a comment.
            "parent_comment_id": (
                str(comment.parent_comment_id) if comment.parent_comment_id else None
            ),
            "is_thread": comment.is_thread,
            # RADD-1318: where it came from when no person typed it (null = a person).
            "origin": comment.origin,
            # A ref, not a bare id: a notification naming "3f2a-…" as the writer is unreadable.
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
    *,
    origin: CommentOrigin | None = None,
) -> CommentRead:
    binding, project = await _parent_scope(session, entity_type, entity_id)
    if data.is_thread or data.anchor is not None:
        await binding.require_read(session, actor, entity_id, project)
    permissions = await binding.require_write(session, actor, entity_id, project)
    return await create_authorized_comment(
        session, entity_id, data, actor, entity_type=entity_type, permissions=permissions,
        origin=origin,
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
    origin: CommentOrigin | None = None,
) -> CommentRead:
    """Write a comment whose authorisation the CALLER has already decided.

    For callers admitting by another rule: the requester portal admits by
    relationship (RADD-796), and a requester holds `comment.write` nowhere. A named
    function rather than a `bypass_authz=True` flag, because such a flag gets
    copied into callers with no business skipping checks. An EMPTY `permissions`
    keeps an unprivileged caller away from the import overrides and internal
    comments, both gated on that set. Downstream (events, mentions, watchers) is
    the one shared write path.
    """
    _check_internal(permissions, data.visibility)
    is_thread = parent_comment_id is None and (data.is_thread or data.anchor is not None)
    if is_thread:
        await lock_thread_parent(session, entity_type, entity_id)
    # Import overrides (author/timestamp) are honored only for a project manager.
    can_import = Permission.PROJECT_MANAGE in permissions
    # An import names the author explicitly. Falling back to the actor would credit
    # the importer with everyone's comments; unmapped identities stay NULL (RADD-1195).
    author_id = data.author_id if (can_import and "author_id" in data.model_fields_set) else actor.id
    occurred_at = data.created_at if (can_import and data.created_at) else None
    comment = Comment(
        entity_type=entity_type,
        entity_id=entity_id,
        author_id=author_id,
        body=data.body,
        is_thread=is_thread,
        anchor=data.anchor.model_dump() if data.anchor else None,
        visibility=data.visibility.value,
        parent_comment_id=parent_comment_id,
        # RADD-1318: an automation's comment is DERIVED, whoever it acts as.
        origin=(origin or (CommentOrigin.AUTOMATION if events.is_automated() else None)),
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


async def toggle_task(
    session: AsyncSession, comment_id: uuid.UUID, data: "tasklists.TaskToggle", actor: User
) -> CommentRead:
    """Tick one checklist box in a comment (RADD-1296) — the SAME gate as
    editing it, checked before the body is compared so a 409 tells a stranger
    nothing. The write is an ordinary edit (history, events, audit)."""
    comment = await _get(session, comment_id)
    _binding, project = await _parent_scope(session, comment.entity_type, comment.entity_id)
    permissions = await _require_author_or(
        session, comment, actor, project, others=Permission.PROJECT_MANAGE
    )
    _check_internal(permissions, comment.visibility)
    try:
        body = tasklists.toggle(comment.body, data)
    except tasklists.TaskToggleConflict as exc:
        raise ConflictError(CommentEntity.COMMENT, reason=str(exc)) from exc
    return await update_comment(session, comment_id, CommentUpdate(body=body), actor)


async def update_comment(
    session: AsyncSession, comment_id: uuid.UUID, data: CommentUpdate, actor: User
) -> CommentRead:
    comment = await _get(session, comment_id)
    root = None
    if comment.parent_comment_id:
        root = await require_thread(session, comment.parent_comment_id, actor)
        if data.visible_to_teams is not None:
            # RADD-1246: a reply may move within its thread's audience, never past it.
            root_teams = (await _team_restrictions(session, [root.id])).get(root.id, set())
            _visibility, narrowed = reply_audience(
                root, root_teams, CommentVisibility(comment.visibility), data.visible_to_teams
            )
            data = data.model_copy(update={"visible_to_teams": sorted(narrowed)})
    binding, project = await _parent_scope(session, comment.entity_type, comment.entity_id)
    permissions = await _require_author_or(
        session, comment, actor, project, others=Permission.PROJECT_MANAGE
    )
    _check_internal(permissions, comment.visibility)
    body_changed = data.body is not None and comment.body != data.body
    previous_teams = (await _team_restrictions(session, [comment.id])).get(comment.id, set())
    if data.body is not None:
        comment.body = data.body
    await session.flush()
    if data.visible_to_teams is not None:
        stored_teams = await _set_teams(session, comment, data.visible_to_teams)
        if root is None and stored_teams != previous_teams:
            # The thread's audience is its replies' ceiling (RADD-1246).
            await narrow_replies(session, comment, stored_teams)
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
    """Delete one comment or reply. A ROOT that still has replies is refused
    (RADD-1477): deleting the first line of a discussion would take every
    answer with it, so the answers go first — the FK cascade stays for
    `delete_for_parent`, where the whole parent is going anyway."""
    comment = await _get(session, comment_id)
    if comment.parent_comment_id:
        await require_thread(session, comment.parent_comment_id, actor)
    binding, project = await _parent_scope(session, comment.entity_type, comment.entity_id)
    permissions = await _require_author_or(
        session, comment, actor, project, others=Permission.COMMENT_DELETE
    )
    _check_internal(permissions, comment.visibility)
    # After the gate, so a stranger learns nothing about the thread's size.
    replies = await reply_count(session, comment.id)
    if replies:
        raise ConflictError(
            CommentEntity.COMMENT,
            reason=f"This comment has {replies} {'reply' if replies == 1 else 'replies'}; delete them first",
        )
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
    """Remove every comment on a parent being destroyed. The polymorphic column has no
    FK cascade (RADD-717); `gc.py` catches any delete path that forgets to call this."""
    result = await session.execute(
        delete(Comment).where(
            Comment.entity_type == entity_type, Comment.entity_id == entity_id
        )
    )
    return result.rowcount or 0


async def set_resolved(
    session: AsyncSession, comment_id: uuid.UUID, actor: User, *, resolved: bool
) -> CommentRead:
    """Resolve or reopen a resolvable root (inline or general discussion), under the
    parent's thread-resolution rule. Idempotent: two people clicking at once is ordinary."""
    comment = await _get(session, comment_id)
    if comment.parent_comment_id:
        raise ConflictError(CommentEntity.COMMENT, reason="Resolve the thread, not an individual reply")
    comment = await require_thread(session, comment_id, actor)
    await lock_thread_parent(session, comment.entity_type, comment.entity_id)
    comment = await require_thread(session, comment_id, actor, lock=True)
    if not comment.is_thread:
        raise ConflictError(CommentEntity.COMMENT, reason="Only a resolvable thread can be resolved")
    from .resolution import require_resolvable

    # RADD-1283: the parent's resolution rule decides, not a hardcoded author-or-manager.
    await require_resolvable(session, comment, actor)
    was_resolved = comment.resolved_at is not None
    if was_resolved != resolved:
        comment.resolved_at = utcnow() if resolved else None
        comment.resolved_by = actor.id if resolved else None
    await session.flush()
    stored_teams = (await _team_restrictions(session, [comment.id])).get(comment.id, set())
    if was_resolved != resolved:  # spec 123: resolving is an update to the record
        await _emit(
            session, CommentEvent.UPDATED, comment, actor.id,
            visible_to_teams=stored_teams,
            diff=[{"field": "resolved", "from": was_resolved, "to": resolved}],
        )
    author = await auth.get_user(session, comment.author_id) if comment.author_id else None
    return _to_read(comment, author, stored_teams, actor if resolved else None).model_copy(
        update={"can_resolve": True}  # whoever just resolved it may unresolve it: same rule
    )


async def annotate_email_signature(session: AsyncSession, comment_id: uuid.UUID, signature: str) -> None:
    """Intake-only metadata on a comment it just created through normal authorization."""
    row = await _get(session, comment_id)
    if signature and signature in row.body:
        row.email_signature = signature
        await session.flush()


async def restore_email_signature(session: AsyncSession, comment_id: uuid.UUID, actor: User) -> None:
    """Use the same read, author, audience, and manager gates as a body edit."""
    await locate(session, comment_id, actor)
    row = await _get(session, comment_id)
    await update_comment(session, comment_id, CommentUpdate(body=row.body), actor)
    row.email_signature = None
    await session.flush()
