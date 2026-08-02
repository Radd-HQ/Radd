import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.exceptions import NotFoundError
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser

from radd.config import settings as config

from . import service
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


@router.post("", response_model=CycleRead, status_code=201)
async def create_cycle(data: CycleCreate, session: Session, user: CurrentUser) -> CycleRead:
    await authz.require(session, user, authz.Permission.CYCLE_CREATE)
    return await service.create_cycle(session, data, today=date.today(), actor_id=user.id)


@router.get("", response_model=list[CycleRead])
async def list_cycles(
    session: Session,
    user: CurrentUser,
    status: Annotated[CycleStatus | None, Query()] = None,
) -> list[CycleRead]:
    await authz.require(session, user, authz.Permission.ITEM_READ)
    today = date.today()
    # Spec 60: team-restricted cycles only reach their members (+ cycle managers).
    cycles, teams_by_cycle = await service.visible_cycles(
        session, user, status=status, today=today
    )
    return [
        service.to_read(cycle, today, teams_by_cycle.get(cycle.id, [])) for cycle in cycles
    ]


async def _require_visible(session: AsyncSession, cycle, user) -> None:
    """404 on a team-restricted cycle the user isn't in (spec 60 — don't reveal it)."""
    if not await service.cycle_visible_to(session, cycle, user):
        raise NotFoundError(CycleEntity.CYCLE, cycle.id)


@router.get("/{cycle_id}", response_model=CycleRead)
async def get_cycle(cycle_id: uuid.UUID, session: Session, user: CurrentUser) -> CycleRead:
    cycle = await service.get_cycle(session, cycle_id)
    await authz.require(
        session, user, authz.Permission.ITEM_READ
    )
    await _require_visible(session, cycle, user)
    team_ids = (await service.team_ids_by_cycle(session, [cycle.id])).get(cycle.id, [])
    return service.to_read(cycle, date.today(), team_ids)


@router.patch("/{cycle_id}", response_model=CycleRead)
async def update_cycle(
    cycle_id: uuid.UUID, data: CycleUpdate, session: Session, user: CurrentUser
) -> CycleRead:
    cycle = await service.get_cycle(session, cycle_id)
    await authz.require(
        session, user, authz.Permission.CYCLE_UPDATE
    )
    return await service.update_cycle(session, cycle_id, data, today=date.today(), actor_id=user.id)


@router.get("/{cycle_id}/stats", response_model=CycleStats)
async def cycle_stats(
    cycle_id: uuid.UUID,
    session: Session,
    user: CurrentUser,
    assignee_id: Annotated[uuid.UUID | None, Query()] = None,
    team_id: Annotated[uuid.UUID | None, Query()] = None,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
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
    await authz.require(
        session, user, authz.Permission.ITEM_READ
    )
    await _require_visible(session, cycle, user)
    counts = await items_service.cycle_state_category_counts(
        session, cycle_id, assignee_id=assignee_id, team_id=team_id, project_id=project_id
    )
    points_total, points_done = await items_service.cycle_points_totals(
        session, cycle_id, assignee_id=assignee_id, team_id=team_id, project_id=project_id
    )
    estimate, logged, remaining = await cycle_time_totals(
        session, cycle_id, assignee_id=assignee_id, team_id=team_id, project_id=project_id
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
    await authz.require(
        session, user, authz.Permission.CYCLE_UPDATE
    )
    return await service.complete_cycle(session, cycle_id, data, today=date.today(), actor=user)


@router.delete("/{cycle_id}", status_code=204)
async def delete_cycle(cycle_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    cycle = await service.get_cycle(session, cycle_id)
    await authz.require(
        session, user, authz.Permission.CYCLE_DELETE
    )
    await service.delete_cycle(session, cycle_id, actor_id=user.id)


# --- recurring series (created via CycleCreate.recurring; managed here) ---


@series_router.get("", response_model=list[CycleSeriesRead])
async def list_series(session: Session, user: CurrentUser) -> list[CycleSeriesRead]:
    await authz.require(session, user, authz.Permission.ITEM_READ)
    rows = await service.list_series(session)
    return [CycleSeriesRead.model_validate(row) for row in rows]


@series_router.patch("/{series_id}", response_model=CycleSeriesRead)
async def update_series(
    series_id: uuid.UUID, data: CycleSeriesUpdate, session: Session, user: CurrentUser
) -> CycleSeriesRead:
    series = await service.get_series(session, series_id)
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
    series = await service.get_series(session, series_id)
    await authz.require(
        session, user, authz.Permission.CYCLE_DELETE
    )
    await service.delete_series(session, series_id, actor_id=user.id)
