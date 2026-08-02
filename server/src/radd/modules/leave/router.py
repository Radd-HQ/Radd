import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.exceptions import ForbiddenError
from radd.modules.auth.deps import CurrentUser
from radd.modules.teams import service as teams_service

from . import service
from .models import LeavePeriod
from .schemas import CurrentLeave, LeaveCalendarEntry, LeaveCreate, LeaveRead

router = APIRouter(prefix="/leave", tags=["leave"])

Session = Annotated[AsyncSession, Depends(get_session)]


async def _read(session: AsyncSession, period: LeavePeriod) -> LeaveRead:
    team_name = None
    if period.team_id is not None:
        team_name = (await teams_service.get_team(session, period.team_id)).name
    return LeaveRead(
        id=period.id,
        user_id=period.user_id,
        team_id=period.team_id,
        team_name=team_name,
        kind=period.kind,
        label=period.label,
        start_date=period.start_date,
        end_date=period.end_date,
        created_by=period.created_by,
    )


@router.post("", response_model=LeaveRead, status_code=201)
async def create_leave(data: LeaveCreate, session: Session, user: CurrentUser) -> LeaveRead:
    period = await service.create(session, user, data)
    return await _read(session, period)


@router.delete("/{period_id}", status_code=204)
async def delete_leave(period_id: uuid.UUID, session: Session, user: CurrentUser) -> Response:
    await service.remove(session, user, period_id)
    return Response(status_code=204)


@router.get("/mine", response_model=list[LeaveRead])
async def my_leave(session: Session, user: CurrentUser) -> list[LeaveRead]:
    return [await _read(session, p) for p in await service.list_for_user(session, user.id)]


@router.get("/holidays", response_model=list[LeaveRead])
async def holidays(session: Session, user: CurrentUser) -> list[LeaveRead]:
    """Team holidays, org-visible — knowing another region is off is the point."""
    return [await _read(session, p) for p in await service.list_holidays(session)]


@router.get("/users/{user_id}", response_model=list[LeaveRead])
async def user_leave(
    user_id: uuid.UUID, session: Session, user: CurrentUser
) -> list[LeaveRead]:
    """A user's personal leave — self, their team stewards, or admins."""
    if not await service.may_manage_user(session, user, user_id):
        raise ForbiddenError("you can only view leave for yourself or your team's members")
    return [await _read(session, p) for p in await service.list_for_user(session, user_id)]


@router.get("/current", response_model=list[CurrentLeave])
async def current(session: Session, user: CurrentUser) -> list[CurrentLeave]:
    """Everyone away TODAY — the app-wide dim + icon indicator's one query."""
    return await service.current(session, date.today())


@router.get("/calendar", response_model=list[LeaveCalendarEntry])
async def calendar(
    start: date, end: date, session: Session, user: CurrentUser
) -> list[LeaveCalendarEntry]:
    """Absence spans overlapping [start, end], holidays pre-expanded per member
    (the timesheet joins these onto its day grid)."""
    return await service.calendar(session, start, end)
