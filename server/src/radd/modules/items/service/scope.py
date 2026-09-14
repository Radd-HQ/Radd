"""Shared authorized item-ID query for counts, bulk selection and aggregates."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth import authz
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project

from .. import slq
from ..filters import ItemListFilters
from ..listing import apply_filters, cf_definitions
from ..models import WorkItem
from .visibility import denied_slq_fields, relation_read_clause


async def visible_ids_query(
    session: AsyncSession,
    *,
    actor: User,
    filters: ItemListFilters,
    q: str | None,
):
    """The shared SELECT WorkItem.id builder behind /items/ids and /items/count:
    same filter surface + visibility as list_items. Returns (query, slq_order)."""
    scoped_project: Project | None = None
    if filters.project_id:
        scoped_project = await projects_service.get_project(session, filters.project_id)
        scoped_perms = await authz.require(
            session, actor, Permission.ITEM_READ, project=scoped_project
        )
        readable = {scoped_project.id: scoped_perms}
    else:
        readable = await authz.require_anywhere(session, actor, Permission.ITEM_READ)

    query = select(WorkItem.id)
    if scoped_project is None:
        # Cross-project: constrain to projects the actor can read UP FRONT so
        # both the count and the ids honor visibility (RADD-672: item.read
        # anywhere, not the global atom a scoped key never holds).
        query = query.where(WorkItem.project_id.in_(readable.keys()))
    # RADD-817: ids/count share the same relation row filter as the list.
    relation_clause = await relation_read_clause(session, actor, readable)
    if relation_clause is not None:
        query = query.where(relation_clause)
    query = await apply_filters(session, query, filters, scoped_project)
    order: tuple = ()
    if q and q.strip():
        compiled = await slq.compile_query(
            session,
            slq.parse(q),
            definitions_by_key=await cf_definitions(session, scoped_project),
            current_user_id=actor.id,
            project_id=filters.project_id,
            denied_fields=await denied_slq_fields(session, actor, scoped_project),
        )
        if compiled.where is not None:
            query = query.where(compiled.where)
        # RADD-1176: a state-backed sort joins the workflow row it orders by.
        for target, onclause in compiled.joins:
            query = query.join(target, onclause)
        order = compiled.order
    return query, order

