"""Visible view windows, with search and scope applied before pagination."""
import uuid

from sqlalchemy import false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import ilike_term
from radd.modules.access import service as access
from radd.modules.auth import authz
from radd.modules.auth.models import User
from .models import View


async def query(session: AsyncSession, actor: User, *, project_id: uuid.UUID | None = None,
                include_global: bool = True, global_only: bool = False, q: str = "",
                view_type: str | None = None, exclude_type: str | None = None):
    stmt = select(View)
    if not await authz.readable_projects(session, actor):
        return stmt.where(false())
    stmt = stmt.where(await access.shared_resource_visible_clause(
        session, actor, "view", resource_id=View.id, owner_id=View.owner_id,
        global_access=View.global_access))
    if global_only:
        stmt = stmt.where(View.project_id.is_(None))
    elif project_id is not None:
        scoped = View.project_id == project_id
        stmt = stmt.where(or_(scoped, View.project_id.is_(None)) if include_global else scoped)
    if q.strip():
        stmt = stmt.where(View.name.ilike(ilike_term(q.strip())))
    if view_type is not None:
        stmt = stmt.where(View.view_type == view_type)
    if exclude_type is not None:
        stmt = stmt.where(View.view_type != exclude_type)
    return stmt


async def count(session: AsyncSession, actor: User, **filters) -> int:
    stmt = await query(session, actor, **filters)
    return await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0


async def page(session: AsyncSession, actor: User, *, limit: int | None = None,
               offset: int = 0, **filters):
    stmt = await query(session, actor, **filters)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    stmt = stmt.order_by(View.position, View.name, View.id).offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(await session.scalars(stmt)), total
