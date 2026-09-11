"""Shared dashboard search/count/windows without loading every definition."""
from sqlalchemy import false, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import ilike_term
from radd.modules.access import service as access
from radd.modules.auth import authz
from radd.modules.auth.models import User
from .models import Dashboard


async def query(session: AsyncSession, actor: User, *, q: str = ""):
    stmt = select(Dashboard)
    if not await authz.readable_projects(session, actor):
        return stmt.where(false())
    stmt = stmt.where(await access.shared_resource_visible_clause(
        session, actor, "dashboard", resource_id=Dashboard.id, owner_id=Dashboard.owner_id,
        global_access=Dashboard.global_access))
    if q.strip():
        stmt = stmt.where(Dashboard.name.ilike(ilike_term(q.strip())))
    return stmt


async def count(session: AsyncSession, actor: User, *, q: str = "") -> int:
    stmt = await query(session, actor, q=q)
    return await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0


async def page(session: AsyncSession, actor: User, *, q: str = "", limit: int | None = None,
               offset: int = 0):
    stmt = await query(session, actor, q=q)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    stmt = stmt.order_by(Dashboard.position, Dashboard.name, Dashboard.id).offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(await session.scalars(stmt)), total
