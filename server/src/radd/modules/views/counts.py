"""Batched membership counts for view types with a sidebar section of their own
(`ViewTypeSpec.sidebar_section`). Invisible or stale views are omitted, never
errored; quick filters are not applied (base membership). Items are scoped as
`GET /items` renders the view: archived excluded, readable projects only."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth import authz
from radd.modules.auth.models import User
from radd.modules.items import service as items_service, slq
from radd.modules.items.models import WorkItem
from radd.modules.groups import service as groups_service
from radd.modules.teams import service as teams_service
from radd.modules.projects import service as projects_service

from .models import View
from .service import _grant_level, _scope_definitions, _shares_by_view


async def view_counts(
    session: AsyncSession,
    *,
    actor: User,
    view_ids: list[uuid.UUID],
    extra_q: str | None = None,
) -> dict[uuid.UUID, int]:
    """`{view_id: count}` for every requested view the actor can see (owner, share
    grantee or global_access). Unknown or invisible ids are omitted, and so is a
    view whose stored query no longer compiles."""
    unique_ids = list(dict.fromkeys(view_ids))
    if not unique_ids:
        return {}
    views = list(
        (await session.execute(select(View).where(View.id.in_(unique_ids)))).scalars()
    )
    if not views:
        return {}
    # The member floor (readable projects), same bar as the view list.
    readable_map = await authz.readable_projects(session, actor)
    readable_ids = set(readable_map)
    if not readable_ids:
        return {}
    # RADD-817: badges count exactly what the list shows.
    relation_clause = await items_service.relation_read_clause(session, actor, readable_map)
    shares_map = await _shares_by_view(session, [v.id for v in views])
    team_ids = await teams_service.user_team_ids(session, actor.id)
    group_ids = await groups_service.user_group_ids(session, actor.id)

    counts: dict[uuid.UUID, int] = {}
    for view in views:
        grant = _grant_level(view, shares_map.get(view.id, []), actor.id, team_ids, group_ids)
        if view.owner_id != actor.id and grant is None:
            continue  # invisible (spec 57) — omitted, not errored
        count = await _count_view(
            session, view, actor, readable_ids, extra_q=extra_q, relation_clause=relation_clause
        )
        if count is not None:
            counts[view.id] = count
    return counts


async def _count_view(
    session: AsyncSession,
    view: View,
    actor: User,
    readable_ids: set[uuid.UUID],
    extra_q: str | None = None,
    relation_clause=None,
) -> int | None:
    """One compiled-SLQ count for a VISIBLE view; None = omit (stale query)."""
    stmt = (
        select(func.count())
        .select_from(WorkItem)
        # The read path hides archived items by default (spec 38) — so does the badge.
        .where(WorkItem.archived_at.is_(None))
    )
    if relation_clause is not None:
        stmt = stmt.where(relation_clause)
    if view.project_id is not None:
        if view.project_id not in readable_ids:
            return 0  # visible view, unreadable items — the list they'd see is empty
        stmt = stmt.where(WorkItem.project_id == view.project_id)
    else:
        stmt = stmt.where(WorkItem.project_id.in_(readable_ids))
    text = (view.query or "").strip()
    extra = (extra_q or "").strip()
    # The view's own query AND the caller's extra filter compile separately
    # against the same scope, and each contributes a WHERE — predicate-level
    # composition, no string splicing.
    project = (
        await projects_service.get_project(session, view.project_id)
        if view.project_id is not None
        else None
    )
    denied = await items_service.denied_slq_fields(session, actor, project)
    for query_text in (text, extra):
        if not query_text:
            continue
        try:
            definitions = await _scope_definitions(session, view.project_id)
            compiled = await slq.compile_query(
                session,
                slq.parse(query_text),
                definitions_by_key=definitions,
                current_user_id=actor.id,
                project_id=view.project_id,
                denied_fields=denied,
            )
        except slq.SlqError:
            # Stale query — or one naming a field this actor can't read
            # (RADD-840): the badge is a COUNT, the exact oracle to close.
            return None
        if compiled.where is not None:
            stmt = stmt.where(compiled.where)
    return (await session.execute(stmt)).scalar_one()
