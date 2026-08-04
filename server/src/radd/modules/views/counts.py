"""Batched view membership counts (spec 64) — the sidebar queue badges.

POST /views/counts resolves each requested view to a compiled-SLQ
`SELECT count(*)` over work_items. Visibility mirrors the view read path
(spec 57): views the actor can't see are silently OMITTED, never errored —
a batch of badges must not fail because one id went stale or private.
Quick filters are deliberately NOT applied: the badge is the view's base
membership count. Items are scoped like `GET /items` renders the view:
archived items excluded, and only projects where the actor holds item.read
count (so the number matches the rows they would actually see).
"""

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
    """`{view_id: count}` for every REQUESTED view the actor can see (spec 57
    visibility: owner / share grantee / global_access — plus the list_views
    membership gate, global item.read). Unknown or invisible ids are omitted;
    a view whose stored query no longer compiles is omitted too (a drifted
    registry shouldn't take the whole batch down)."""
    unique_ids = list(dict.fromkeys(view_ids))
    if not unique_ids:
        return {}
    views = list(
        (await session.execute(select(View).where(View.id.in_(unique_ids)))).scalars()
    )
    if not views:
        return {}
    # The member floor, same bar as list_views (RADD-788). This used to read the
    # GLOBAL item.read atom and return {} when it was absent — which for a
    # project-scoped member meant every queue badge silently vanished rather than
    # erroring, the harder failure to notice.
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
        if not readable_ids:
            return 0
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
