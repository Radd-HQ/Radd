"""Listing + SLQ: the filtered/paginated list and the live SLQ validation."""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth import authz
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.modules.fields import service as fields
from radd.modules.fields.models import FieldDefinition
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project

from .. import slq
from ..filters import ItemListFilters
from ..hydration import hydrate
from ..listing import apply_filters, cf_definitions
from ..models import WorkItem
from ..schemas import ItemRead
from .visibility import (
    attach_capabilities,
    relation_read_clause,
    _builtin_read_denied,
    _field_ctx,
    _filter_read,
    _internal_visible,
    denied_slq_fields,
)


async def validate_slq(
    session: AsyncSession, *, actor: User, q: str, project_id: uuid.UUID | None = None
) -> None:
    """Parse + compile an SLQ draft WITHOUT executing it: the live validation
    behind the editors' status lines. Full grammar + field/label resolution
    (cheap registry/label lookups), zero work_items I/O — execution only
    happens when a surface actually runs the query. Raises SlqError (-> 422
    {detail, position}); a blank draft is trivially valid.
    """
    if not q.strip():
        return
    project = None
    if project_id is not None:
        project = await projects_service.get_project(session, project_id)
        await authz.require(session, actor, Permission.ITEM_READ, project=project)
    else:
        await authz.require_member(session, actor)  # RADD-788
    await slq.compile_query(
        session,
        slq.parse(q),
        definitions_by_key=await cf_definitions(session, project),
        current_user_id=actor.id,
        project_id=project_id,
        denied_fields=await denied_slq_fields(session, actor, project),
    )


async def list_items(
    session: AsyncSession,
    *,
    actor: User,
    filters: ItemListFilters,
    q: str | None = None,
    limit: int,
    offset: int,
) -> list[ItemRead]:
    projects: dict[uuid.UUID, Project] = {}
    permissions: dict[uuid.UUID, frozenset[Permission]] = {}
    if filters.project_id:
        project = await projects_service.get_project(session, filters.project_id)
        projects[project.id] = project
        permissions[project.id] = await authz.require(
            session, actor, Permission.ITEM_READ, project=project
        )
    else:
        # Cross-project listing (RADD-672): item.read ANYWHERE — the global atom
        # would refuse a spec-113 key scoped to one project — and the query is
        # constrained to the readable projects UP FRONT, so LIMIT counts only
        # rows the actor may see (the visibility post-filter below used to run
        # after pagination, so a scoped principal could page through nothing but
        # unreadable rows while readable items sat past the limit).
        readable = await authz.require_anywhere(session, actor, Permission.ITEM_READ)

    query = select(WorkItem)
    if not filters.project_id:
        query = query.where(WorkItem.project_id.in_(readable.keys()))
    # RADD-817: the relation row filter — item.read@own/@team narrows WHICH rows,
    # per project, in the same WHERE every count/board/report shares.
    relation_clause = await relation_read_clause(
        session, actor, permissions if filters.project_id else readable
    )
    if relation_clause is not None:
        query = query.where(relation_clause)
    query = await apply_filters(session, query, filters, projects.get(filters.project_id))
    order: tuple = ()
    if q and q.strip():
        # SLQ (spec 10): ANDed with the structured params; its ORDER BY (if any)
        # leads the ordering, created-desc stays as the tiebreak/default.
        compiled = await slq.compile_query(
            session,
            slq.parse(q),
            definitions_by_key=await cf_definitions(session, projects.get(filters.project_id)),
            current_user_id=actor.id,
            project_id=filters.project_id,
            denied_fields=await denied_slq_fields(
                session, actor, projects.get(filters.project_id)
            ),
        )
        if compiled.where is not None:
            query = query.where(compiled.where)
        order = compiled.order
    # No explicit ORDER BY → manual rank order (spec 24, drag-to-reorder); rank is
    # backfilled/assigned newest-first so this matches the old created-desc default
    # while being reorderable. Explicit sorts keep created-desc as the tiebreak.
    default_order = () if order else (WorkItem.rank.asc(),)
    query = (
        query.order_by(*order, *default_order, WorkItem.created_at.desc()).limit(limit).offset(offset)
    )
    items = list((await session.execute(query)).scalars())

    for pid in {i.project_id for i in items} - projects.keys():
        project = await projects_service.get_project(session, pid)
        projects[pid] = project
        permissions[pid] = await authz.effective_permissions(session, actor, project=project)
    visible = [i for i in items if authz.holds_base(permissions[i.project_id], Permission.ITEM_READ)]
    reads = await hydrate(
        session,
        visible,
        internal_visible=_internal_visible(permissions),
        actor_id=actor.id,
        readable_project_ids=frozenset(await authz.readable_projects(session, actor)),
    )

    definitions: dict[uuid.UUID, Sequence[FieldDefinition]] = {}
    ctxs: dict[uuid.UUID, fields.FieldAccessContext] = {}
    builtin_denied: dict[uuid.UUID, list[str]] = {}
    for pid in {r.project_id for r in reads}:
        definitions[pid] = await fields.definitions_for_project(session, projects[pid])
        ctxs[pid] = await _field_ctx(
            session, actor, projects[pid], permissions[pid], definitions[pid]
        )
        builtin_denied[pid] = await _builtin_read_denied(session, projects[pid], ctxs[pid])
    filtered = [
        _filter_read(r, definitions[r.project_id], ctxs[r.project_id], builtin_denied[r.project_id])
        for r in reads
    ]
    # RADD-842: the actor's per-row verdict rides every list read, so boards
    # and bulk selection can disable up front instead of edit-then-error.
    return await attach_capabilities(
        session, actor, filtered, {i.id: i for i in visible}, permissions
    )
