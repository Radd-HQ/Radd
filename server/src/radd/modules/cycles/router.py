import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.apitypes import TOTAL_COUNT_HEADER
from radd.exceptions import NotFoundError
from radd.modules.auth import authz
from radd.modules.auth.deps import Actor, CurrentUser

from radd.config import settings as config

from . import service, directory
from .schemas import (
    CycleComplete,
    CycleCompleteResult,
    CycleCreate,
    CycleRead,
    CycleSeriesRead,
    CycleSeriesUpdate,
    CycleStats,
    CycleUpdate,
)
from .types import CycleEntity, CycleStatus

router = APIRouter(prefix="/cycles", tags=["cycles"])
series_router = APIRouter(prefix="/cycle-series", tags=["cycles"])

Session = Annotated[AsyncSession, Depends(get_session)]


async def _require_cycle_write(
    session: AsyncSession, user, permission: authz.Permission, project_id: uuid.UUID | None
) -> None:
    """RADD-1291: the instance-wide cycle atom, OR managing the cycle's home
    project — so a team lead can run their project's sprints without being a
    cycle admin for the whole instance. An instance cycle needs the atom."""
    if await authz.holds(session, user, permission):
        return
    if project_id is not None:
        from radd.modules.projects import service as projects_service

        project = await projects_service.get_project(session, project_id)
        await authz.require(session, user, authz.Permission.PROJECT_MANAGE, project=project)
        return
    await authz.require(session, user, permission)


@router.post("", response_model=CycleRead, status_code=201)
async def create_cycle(data: CycleCreate, session: Session, user: CurrentUser) -> CycleRead:
    await _require_cycle_write(session, user, authz.Permission.CYCLE_CREATE, data.project_id)
    return await service.create_cycle(session, data, today=date.today(), actor_id=user.id)


@router.get("", response_model=list[CycleRead])
async def list_cycles(
    session: Session,
    user: Actor,
    response: Response,
    status: Annotated[CycleStatus | None, Query()] = None,
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    include_completed: bool = True,
    exclude_id: uuid.UUID | None = None,
    dated_only: bool = False,
    recent_first: bool = False,
    project_id: Annotated[uuid.UUID | None, Query(description="Only cycles homed in, or holding issues of, this project")] = None,
) -> list[CycleRead]:
    if not await authz.holds(session, user, authz.Permission.CYCLE_READ):
        response.headers[TOTAL_COUNT_HEADER] = "0"
        return []
    today = date.today()
    cycles, teams_by_cycle, total = await directory.page(
        session, user, status=status, today=today, q=q, limit=limit, offset=offset,
        include_completed=include_completed, exclude_id=exclude_id,
        dated_only=dated_only, recent_first=recent_first, project_id=project_id,
    )
    response.headers[TOTAL_COUNT_HEADER] = str(total)
    return [service.to_read(cycle, today, teams_by_cycle.get(cycle.id, [])) for cycle in cycles]


@router.get("/summary", response_model=dict[CycleStatus, int])
async def cycle_summary(
    session: Session, user: Actor, q: Annotated[str, Query(max_length=200)] = "",
):
    if not await authz.holds(session, user, authz.Permission.CYCLE_READ):
        return {}
    return await directory.counts(session, user, q=q)


async def _require_visible(session: AsyncSession, cycle, user) -> None:
    """404 on a team-restricted cycle the user isn't in (spec 60 — don't reveal it)."""
    if not await service.cycle_visible_to(session, cycle, user):
        raise NotFoundError(CycleEntity.CYCLE, cycle.id)


@router.get("/{cycle_id}", response_model=CycleRead)
async def get_cycle(cycle_id: uuid.UUID, session: Session, user: Actor) -> CycleRead:
    cycle = await service.get_cycle(session, cycle_id)
    await authz.require(session, user, authz.Permission.CYCLE_READ)
    await _require_visible(session, cycle, user)
    team_ids = (await service.team_ids_by_cycle(session, [cycle.id])).get(cycle.id, [])
    return service.to_read(cycle, date.today(), team_ids)


@router.patch("/{cycle_id}", response_model=CycleRead)
async def update_cycle(
    cycle_id: uuid.UUID, data: CycleUpdate, session: Session, user: CurrentUser
) -> CycleRead:
    cycle = await service.get_cycle(session, cycle_id)
    await _require_visible(session, cycle, user)
    await _require_cycle_write(session, user, authz.Permission.CYCLE_UPDATE, cycle.project_id)
    if "project_id" in data.model_fields_set and data.project_id != cycle.project_id:
        # Re-homing moves a cycle into another project's hands: that project's
        # managers (or a cycle admin) must agree too.
        await _require_cycle_write(session, user, authz.Permission.CYCLE_UPDATE, data.project_id)
    return await service.update_cycle(session, cycle_id, data, today=date.today(), actor_id=user.id)


@router.get("/{cycle_id}/stats", response_model=CycleStats)
async def cycle_stats(
    cycle_id: uuid.UUID,
    session: Session,
    user: CurrentUser,
    assignee_id: Annotated[uuid.UUID | None, Query()] = None,
    team_id: Annotated[uuid.UUID | None, Query()] = None,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
    q: str | None = None,
) -> CycleStats:
    """Cycle-page header metrics: per-category counts + time totals, honoring the
    same assignee/team filters the page applies to its item list. `project_id`
    narrows the all-projects cycle to one project's slice — project-scoped
    surfaces (planning page, project views) pass it so a DEV handle never shows
    TD time."""
    # Deferred: items/timelogging both (transitively) import cycles — see complete_cycle.
    from radd.modules.items import service as items_service
    from radd.modules.settings import service as settings_service
    from radd.modules.settings.types import SettingKey
    from radd.modules.timelogging.duration import format_duration
    from radd.modules.timelogging.timesheet import cycle_time_totals

    cycle = await service.get_cycle(session, cycle_id)
    await authz.require(session, user, authz.Permission.CYCLE_READ)
    await _require_visible(session, cycle, user)
    counts = await items_service.cycle_state_category_counts(
        session, cycle_id, actor=user, q=q, assignee_id=assignee_id, team_id=team_id, project_id=project_id
    )
    points_total, points_done = await items_service.cycle_points_totals(
        session, cycle_id, actor=user, q=q, assignee_id=assignee_id, team_id=team_id, project_id=project_id
    )
    estimate, logged, remaining = await cycle_time_totals(
        session, cycle_id, actor=user, q=q, assignee_id=assignee_id, team_id=team_id, project_id=project_id
    )
    # Hours-per-day is a GLOBAL scalar (spec 67 follow-up: instance-only).
    hours_per_day = int(
        await settings_service.resolve(session, SettingKey.TIMELOG_HOURS_PER_DAY)
    )

    def fmt(seconds: int) -> str:
        return format_duration(
            seconds, hours_per_day=hours_per_day, days_per_week=config.timelog_days_per_week
        )

    return CycleStats(
        total=sum(counts.values()),
        by_category=counts,
        estimate_seconds=estimate,
        logged_seconds=logged,
        remaining_seconds=remaining,
        estimate=fmt(estimate),
        logged=fmt(logged),
        remaining=fmt(remaining),
        points_total=points_total,
        points_done=points_done,
    )


@router.post("/{cycle_id}/complete", response_model=CycleCompleteResult)
async def complete_cycle(
    cycle_id: uuid.UUID, data: CycleComplete, session: Session, user: CurrentUser
) -> CycleCompleteResult:
    """Jira-style sprint close: open items move to `move_open_to` (null = backlog),
    the cycle is stamped completed, the target optionally starts today, and drafts
    are topped up per the `cycle_drafts_ahead` setting. Item moves run as the
    caller, so item.update is enforced per project by the items service."""
    cycle = await service.get_cycle(session, cycle_id)
    await _require_cycle_write(session, user, authz.Permission.CYCLE_UPDATE, cycle.project_id)
    return await service.complete_cycle(session, cycle_id, data, today=date.today(), actor=user)


@router.delete("/{cycle_id}", status_code=204)
async def delete_cycle(cycle_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    cycle = await service.get_cycle(session, cycle_id)
    await _require_visible(session, cycle, user)
    await _require_cycle_write(session, user, authz.Permission.CYCLE_DELETE, cycle.project_id)
    await service.delete_cycle(session, cycle_id, actor_id=user.id)


# --- recurring series (created via CycleCreate.recurring; managed here) ---


@series_router.get("", response_model=list[CycleSeriesRead])
async def list_series(
    session: Session, user: CurrentUser, response: Response,
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[CycleSeriesRead]:
    if not await authz.holds(session, user, authz.Permission.CYCLE_READ):
        response.headers[TOTAL_COUNT_HEADER] = "0"
        return []
    rows, total = await directory.series_page(session, q=q, limit=limit, offset=offset)
    response.headers[TOTAL_COUNT_HEADER] = str(total)
    return [CycleSeriesRead.model_validate(row) for row in rows]


@series_router.patch("/{series_id}", response_model=CycleSeriesRead)
async def update_series(
    series_id: uuid.UUID, data: CycleSeriesUpdate, session: Session, user: CurrentUser
) -> CycleSeriesRead:
    await service.get_series(session, series_id)
    await authz.require(
        session, user, authz.Permission.CYCLE_UPDATE
    )
    updated = await service.update_series(
        session, series_id, data, today=date.today(), actor_id=user.id
    )
    return CycleSeriesRead.model_validate(updated)


@series_router.delete("/{series_id}", status_code=204)
async def delete_series(series_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    """Stop recurring — existing cycles are untouched, only auto-provisioning ends."""
    await service.get_series(session, series_id)
    await authz.require(
        session, user, authz.Permission.CYCLE_DELETE
    )
    await service.delete_series(session, series_id, actor_id=user.id)
