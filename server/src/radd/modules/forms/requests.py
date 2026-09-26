"""The requester's view of their own requests (RADD-796/797/798).

A requester is admitted by RELATIONSHIP, never by `item.read`: they reported
it, or it was filed for a team they are in — one rule, `visible_condition`,
used by every read and write here.

Reporting must not become a back door (RADD-785): no labels, custom fields,
worklogs, history or internal comments, trimmed in the QUERY, so even derived
numbers (comment count, "who spoke last") see public comments only. An
invisible request is a 404, never a 403 — a refusal confirms the key exists.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ForbiddenError, NotFoundError
from radd.modules.auth.models import User
from radd.modules.comments import service as comments_service
from radd.modules.comments.types import CommentOrigin, CommentParentType, CommentVisibility
from radd.modules.items.models import WorkItem
from radd.modules.projects import service as projects_service
from radd.modules.teams import service as teams_service
from radd.modules.workflow.models import State

from .schemas import (
    PortalProjectRef,
    PortalRequestComment,
    PortalRequestDetail,
    PortalRequestRead,
)
from .types import FormEntity

#: A requester's list is a recent-activity list, not an archive.
DEFAULT_LIMIT = 50


async def visible_condition(session: AsyncSession, actor: User) -> ColumnElement[bool]:
    """THE admission rule: reported by you, or filed for a team you are in.

    One expression, used by every read and write below — and since RADD-823 it
    is COMPOSED from the registered item relations (`own` ∪ `team`) rather than
    restating their columns: this function was the relation pattern shipping in
    miniature (trap-aware — the trimming is in the QUERY, not the serializer),
    and it becomes the registry's first consumer instead of a copy that would
    drift. `team` is the column the form's team picker writes (RADD-798).
    """
    from radd.kernel import registries
    from radd.modules.auth import authz

    relation_actor = await authz.relation_actor(session, actor)
    specs = registries.relations_for("item")
    return or_(specs["own"].where(relation_actor), specs["team"].where(relation_actor))


async def _comment_signals(
    session: AsyncSession, items: list[WorkItem]
) -> dict[uuid.UUID, tuple[int, bool]]:
    """`{item_id: (public_count, awaiting_requester)}` in one query over the
    comments module's PUBLIC-only seam, so no derived number can describe the
    internal thread.

    `awaiting_requester`: the newest public comment by someone else is STRICTLY
    newer than the requester's own newest. Strict because `created_at` is
    transaction time — comments written in one transaction tie, and a tie must
    not claim somebody answered. Classified by ORIGIN (RADD-1318): an
    automation's comment is counted but answers nobody; the requester's own
    inbound mail is their reply even with no account behind it.
    """
    item_ids = [item.id for item in items]
    if not item_ids:
        return {}
    rows = await comments_service.public_comment_times(session, item_ids)
    reporters = {item.id: item.reporter_id for item in items}
    counts: dict[uuid.UUID, int] = {}
    mine: dict[uuid.UUID, object] = {}
    theirs: dict[uuid.UUID, object] = {}
    for entity_id, author_id, created_at, origin in rows:
        counts[entity_id] = counts.get(entity_id, 0) + 1
        # RADD-1318: decided by ORIGIN, not "the author is SYSTEM". An
        # automation's comment is not an answer whoever it acts as; the
        # requester's own mail IS their reply even when no account backs it.
        if origin == CommentOrigin.AUTOMATION:
            continue  # neither bucket: it is not the requester, and it is not an answer
        if origin == CommentOrigin.INBOUND_MAIL or author_id == reporters.get(entity_id):
            bucket = mine
        elif author_id is None:
            continue
        else:
            bucket = theirs
        current = bucket.get(entity_id)
        if current is None or created_at > current:
            bucket[entity_id] = created_at
    signals: dict[uuid.UUID, tuple[int, bool]] = {}
    for item_id in item_ids:
        answered = theirs.get(item_id)
        replied = mine.get(item_id)
        signals[item_id] = (
            counts.get(item_id, 0),
            answered is not None and (replied is None or answered > replied),
        )
    return signals


async def _hydrate(
    session: AsyncSession, pairs: list[tuple[WorkItem, State | None]]
) -> list[PortalRequestRead]:
    """Rows with the status a requester actually needs (RADD-797)."""
    if not pairs:
        return []
    items = [item for item, _ in pairs]
    project_ids = {item.project_id for item in items}
    projects = {
        p.id: p for p in await projects_service.list_projects(session) if p.id in project_ids
    }
    keys = await projects_service.project_keys(session, list(project_ids))
    signals = await _comment_signals(session, items)
    names = await _people(session, {i.assignee_id for i in items if i.assignee_id})
    releases = await _releases(session, {i.release_id for i in items if i.release_id})
    teams = await _teams(session, {i.team_id for i in items if i.team_id})

    out: list[PortalRequestRead] = []
    for item, state in pairs:
        project = projects.get(item.project_id)
        if project is None:  # a project removed under them — not their problem
            continue
        count, awaiting = signals.get(item.id, (0, False))
        out.append(
            PortalRequestRead(
                key=f"{keys[project.id]}-{item.number}",
                title=item.title,
                state=state.name if state else "",
                state_category=state.category if state else "",
                project=PortalProjectRef(id=project.id, key=project.key, name=project.name),
                assignee=names.get(item.assignee_id) if item.assignee_id else None,
                release=releases.get(item.release_id) if item.release_id else None,
                team=teams.get(item.team_id) if item.team_id else None,
                team_id=item.team_id,
                comment_count=count,
                # The "someone answered you" marker. Computed over PUBLIC
                # comments, so an internal note never lights up a requester's
                # row — which would tell them something was said that they are
                # not allowed to read.
                awaiting_requester=awaiting,
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
        )
    return out


async def _people(session: AsyncSession, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Assignee NAMES only. The people directory is member-floor readable
    (RADD-769) and carries no email, role or history, so naming who holds a
    request is not new exposure."""
    if not user_ids:
        return {}
    rows = await session.execute(select(User.id, User.name).where(User.id.in_(user_ids)))
    return dict(rows.all())


async def _releases(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    """The version that shipped it — the payoff of the whole service-desk loop,
    and until now the one part that never reached the person who asked."""
    if not ids:
        return {}
    from radd.modules.releases import service as releases_service

    found = await releases_service.releases_by_ids(session, ids)
    return {release_id: release.version for release_id, release in found.items()}


async def _teams(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    found = await teams_service.teams_by_ids(session, list(ids))
    return {team_id: team.name for team_id, team in found.items()}


# --- the surfaces -------------------------------------------------------------


async def list_my_requests(
    session: AsyncSession, actor: User, limit: int = DEFAULT_LIMIT
) -> list[PortalRequestRead]:
    """Everything this person may follow: what they filed, plus what was shared
    with a team they belong to."""
    rows = await session.execute(
        select(WorkItem, State)
        .join(State, State.id == WorkItem.state_id, isouter=True)
        .where(await visible_condition(session, actor))
        .where(WorkItem.archived_at.is_(None))
        .order_by(WorkItem.updated_at.desc())
        .limit(limit)
    )
    return await _hydrate(session, list(rows.all()))


async def _require_visible(session: AsyncSession, actor: User, key: str) -> WorkItem:
    """Resolve `PROJ-123` under the admission rule, or 404.

    NOT 403: a refusal would confirm the key names a real issue, and whether one
    exists is not something a requester is entitled to learn.
    """
    from radd.modules.items import service as items_service

    # Reuse the items module's own key parser rather than re-splitting
    # `PROJ-123` here — two readings of a key is two things to keep in step.
    found = await items_service.find_item_by_key(session, key)
    if found is None:
        raise NotFoundError(FormEntity.FORM, key)
    # Re-select under the admission rule: resolving the key says the issue
    # exists, which is not the same as this person being allowed to see it.
    item = await session.scalar(
        select(WorkItem)
        .where(WorkItem.id == found.id)
        .where(await visible_condition(session, actor))
        .where(WorkItem.archived_at.is_(None))
    )
    if item is None:
        raise NotFoundError(FormEntity.FORM, key)
    return item


async def get_request(session: AsyncSession, actor: User, key: str) -> PortalRequestDetail:
    """One request, as its requester may see it: the description, where it is,
    who holds it, and the PUBLIC conversation."""
    item = await _require_visible(session, actor, key)
    state = await session.get(State, item.state_id) if item.state_id else None
    [row] = await _hydrate(session, [(item, state)])

    comments = await comments_service.public_comments_for_item(session, item.id)
    authors = await _people(session, {c.author_id for c in comments})
    return PortalRequestDetail(
        **row.model_dump(),
        description=item.description or "",
        email_signature=item.email_signature,
        comments=[
            PortalRequestComment(
                id=c.id,
                author=authors.get(c.author_id, ""),
                author_is_me=c.author_id == actor.id,
                body=c.body,
                email_signature=c.email_signature,
                created_at=c.created_at,
            )
            for c in comments
        ],
    )


async def add_request_comment(
    session: AsyncSession, actor: User, key: str, body: str
) -> PortalRequestComment:
    """The reply. A requester who cannot answer a question asked of them is
    stuck, so the view would be useless read-only.

    Visibility is FORCED public here rather than defaulted: this seam must not
    be a way to write into the internal thread, and a default is something a
    caller can override by sending the field.
    """
    from radd.modules.comments.schemas import CommentCreate

    body = body.strip()
    if not body:
        raise ForbiddenError("a reply needs a body")
    item = await _require_visible(session, actor, key)
    # The relationship IS the grant here, exactly as it is for the submit
    # itself: a requester holds `comment.write` nowhere. `permissions` is left
    # EMPTY on purpose — that is what makes the internal-visibility check below
    # refuse, so this seam cannot become a way to write an internal note.
    created = await comments_service.create_authorized_comment(
        session,
        item.id,
        CommentCreate(body=body, visibility=CommentVisibility.PUBLIC),
        actor,
        entity_type=CommentParentType.ITEM.value,
        origin=CommentOrigin.PORTAL,
    )
    return PortalRequestComment(
        id=created.id,
        author=actor.name,
        author_is_me=True,
        body=created.body,
        created_at=created.created_at,
    )
