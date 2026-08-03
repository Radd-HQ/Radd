import uuid
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser
from radd.modules.cycles import service as cycles_service
from radd.modules.items.enums import ItemKind
from radd.modules.projects import service as projects_service

from . import service
from .schemas import (
    BurnupSeries,
    CumulativeFlowBucket,
    SlaReport,
    ThroughputBucket,
    TimeInStateRow,
    VelocityReport,
)
from .service import DEFAULT_WINDOW_DAYS, SLA_REPORT_DEFAULT_WEEKS, SLA_REPORT_MAX_WEEKS
from .types import ReportInterval, ReportMeasure

router = APIRouter(prefix="/reports", tags=["reporting"])

Session = Annotated[AsyncSession, Depends(get_session)]


def _window(start: date | None, end: date | None) -> tuple[date, date]:
    """Resolve + validate a reporting window; default to the last 30 days."""
    end = end or date.today()
    start = start or end - timedelta(days=DEFAULT_WINDOW_DAYS)
    if start > end:
        raise HTTPException(status_code=422, detail="start must be on or before end")
    return start, end


@router.get("/throughput", response_model=list[ThroughputBucket])
async def throughput(
    session: Session,
    user: CurrentUser,
    project_id: uuid.UUID,
    start: date | None = None,
    end: date | None = None,
    interval: ReportInterval = ReportInterval.DAY,
    q: str | None = None,
) -> list[ThroughputBucket]:
    project = await projects_service.get_project(session, project_id)
    await authz.require(session, user, authz.Permission.ITEM_READ, project=project)
    start, end = _window(start, end)
    return await service.throughput(session, project_id, start, end, interval, actor=user, q=q)


@router.get("/cumulative-flow", response_model=list[CumulativeFlowBucket])
async def cumulative_flow(
    session: Session,
    user: CurrentUser,
    project_id: uuid.UUID,
    start: date | None = None,
    end: date | None = None,
    interval: ReportInterval = ReportInterval.DAY,
    q: str | None = None,
) -> list[CumulativeFlowBucket]:
    project = await projects_service.get_project(session, project_id)
    await authz.require(session, user, authz.Permission.ITEM_READ, project=project)
    start, end = _window(start, end)
    return await service.cumulative_flow(session, project_id, start, end, interval, actor=user, q=q)


@router.get("/time-in-state", response_model=list[TimeInStateRow])
async def time_in_state(
    session: Session,
    user: CurrentUser,
    project_id: uuid.UUID,
    kind: Annotated[ItemKind | None, Query()] = None,
    q: str | None = None,
) -> list[TimeInStateRow]:
    project = await projects_service.get_project(session, project_id)
    await authz.require(session, user, authz.Permission.ITEM_READ, project=project)
    return await service.time_in_state(session, project_id, kind, actor=user, q=q)


@router.get("/velocity", response_model=VelocityReport)
async def velocity(
    session: Session,
    user: CurrentUser,
    last: Annotated[int, Query(ge=1, le=50)] = 5,
    measure: ReportMeasure = ReportMeasure.COUNT,
    q: str | None = None,
) -> VelocityReport:
    # Cross-project: the member floor, and the figure carries the scope it was
    # computed over (RADD-788/789).
    await authz.require_member(session, user)
    return await service.velocity(session, last, measure, actor=user, q=q)


@router.get("/burnup", response_model=BurnupSeries)
async def burnup(
    session: Session,
    user: CurrentUser,
    cycle_id: uuid.UUID,
    measure: ReportMeasure = ReportMeasure.COUNT,
    q: str | None = None,
) -> BurnupSeries:
    cycle = await cycles_service.get_cycle(session, cycle_id)
    await authz.require_member(session, user)
    return await service.burnup(session, cycle_id, measure, actor=user, q=q)


@router.get("/sla", response_model=SlaReport)
async def sla(
    session: Session,
    user: CurrentUser,
    project_id: uuid.UUID | None = None,
    weeks: Annotated[int, Query(ge=1, le=SLA_REPORT_MAX_WEEKS)] = SLA_REPORT_DEFAULT_WEEKS,
    q: str | None = None,
) -> SlaReport:
    """Service-desk SLA outcomes per item-created week (spec 63)."""
    if project_id is not None:
        project = await projects_service.get_project(session, project_id)
        await authz.require(session, user, authz.Permission.ITEM_READ, project=project)
    else:
        await authz.require_member(session, user)
    return await service.sla_report(session, project_id, weeks, actor=user, q=q)
