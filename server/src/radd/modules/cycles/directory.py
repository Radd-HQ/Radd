"""Cycle windows filtered by team visibility and derived status in SQL."""
import uuid
from datetime import date

from sqlalchemy import Date, case, cast, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import ilike_term
from radd.modules.auth.models import User
from .models import Cycle, CycleSeries, CycleTeam
from .types import CycleStatus


def status_expression(today: date):
    # Keep the precedence of types.cycle_status, including incomplete legacy dates.
    return case(
        (Cycle.completed_at.is_not(None), CycleStatus.COMPLETED.value),
        (or_(Cycle.start_date.is_(None), Cycle.end_date.is_(None)), CycleStatus.DRAFT.value),
        (Cycle.start_date > today, CycleStatus.UPCOMING.value),
        (Cycle.end_date < today, CycleStatus.COMPLETED.value),
        else_=CycleStatus.ACTIVE.value,
    )


async def visible_query(session: AsyncSession, user: User):
    from radd.modules.auth import authz
    from radd.modules.teams import service as teams

    if authz.Permission.GLOBAL_MANAGE in await authz.effective_permissions(session, user):
        return select(Cycle)
    my_teams = await teams.user_team_ids(session, user.id)
    restricted = select(CycleTeam.cycle_id).where(CycleTeam.cycle_id == Cycle.id).exists()
    member = select(CycleTeam.cycle_id).where(
        CycleTeam.cycle_id == Cycle.id, CycleTeam.team_id.in_(my_teams),
    ).exists()
    return select(Cycle).where(or_(~restricted, member))


def search_clause(q: str):
    return Cycle.name.ilike(ilike_term(q.strip())) if q.strip() else true()


async def series_page(session: AsyncSession, *, q: str = "", limit: int | None = None, offset: int = 0):
    """Global recurring configuration; the router owns the cycle.read gate."""
    query = select(CycleSeries)
    if q.strip():
        query = query.where(CycleSeries.label.ilike(ilike_term(q.strip())))
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    query = query.order_by(CycleSeries.label, CycleSeries.id).offset(offset)
    if limit is not None:
        query = query.limit(limit)
    return list(await session.scalars(query)), total or 0


async def counts(session: AsyncSession, user: User, *, q: str = "", today: date | None = None):
    pivot = status_expression(today or date.today())
    query = (await visible_query(session, user)).where(search_clause(q))
    query = query.with_only_columns(pivot.label("status"), func.count()).group_by(pivot)
    return {status: count for status, count in (await session.execute(query)).all()}


async def recent_completed(session: AsyncSession, *, actor: User | None, limit: int, today: date):
    """Select the last completed cycles after visibility, without loading history."""
    query = await visible_query(session, actor) if actor is not None else select(Cycle)
    finished = func.coalesce(cast(Cycle.completed_at, Date), Cycle.end_date, cast(Cycle.created_at, Date))
    return list(await session.scalars(query.where(status_expression(today) == CycleStatus.COMPLETED.value)
        .order_by(finished.desc(), Cycle.id.desc()).limit(limit)))


async def page(
    session: AsyncSession, user: User, *, q: str = "", status: CycleStatus | None = None,
    include_completed: bool = True, limit: int | None = None, offset: int = 0,
    today: date | None = None, exclude_id: uuid.UUID | None = None,
    dated_only: bool = False, recent_first: bool = False,
):
    from .service import team_ids_by_cycle

    pivot = status_expression(today or date.today())
    query = (await visible_query(session, user)).where(search_clause(q))
    if exclude_id is not None:
        query = query.where(Cycle.id != exclude_id)
    if status is not None:
        query = query.where(pivot == status.value)
    if not include_completed:
        query = query.where(pivot != CycleStatus.COMPLETED.value)
    if dated_only:
        query = query.where(Cycle.start_date.is_not(None), Cycle.end_date.is_not(None))
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    priority = case(
        (pivot == CycleStatus.ACTIVE.value, 0), (pivot == CycleStatus.UPCOMING.value, 1),
        (pivot == CycleStatus.DRAFT.value, 2), else_=3,
    )
    if recent_first:
        query = query.order_by(case((pivot == CycleStatus.ACTIVE.value, 0), else_=1),
                               Cycle.start_date.desc().nullslast(), Cycle.name, Cycle.id)
    else:
        query = query.order_by(priority, Cycle.start_date, Cycle.name, Cycle.id)
    query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)
    rows = list(await session.scalars(query))
    return rows, await team_ids_by_cycle(session, [row.id for row in rows]), total or 0
