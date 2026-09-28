import uuid
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.exceptions import ForbiddenError
from radd.modules.auth import service as auth_service
from radd.modules.auth.deps import CurrentUser
from radd.modules.teams import service as teams_service

from . import service
from .models import LeavePeriod
from .schemas import (
    CurrentLeave,
    LeaveCalendarEntry,
    LeaveCreate,
    LeaveRead,
    TeamLeaveMember,
    TeamLeaveRead,
    TeamLeaveRef,
)

router = APIRouter(prefix="/leave", tags=["leave"])

Session = Annotated[AsyncSession, Depends(get_session)]


async def _reads(session: AsyncSession, periods: list[LeavePeriod]) -> list[LeaveRead]:
    """Rows with their subject's name — one query per kind of subject, not per row."""
    teams = await teams_service.teams_by_ids(
        session, [p.team_id for p in periods if p.team_id is not None]
    )
    users = await auth_service.users_by_ids(
        session, [p.user_id for p in periods if p.user_id is not None]
    )
    return [
        LeaveRead(
            id=p.id,
            user_id=p.user_id,
            user_name=users[p.user_id].name if p.user_id in users else None,
            team_id=p.team_id,
            team_name=teams[p.team_id].name if p.team_id in teams else None,
            kind=p.kind,
            label=p.label,
            start_date=p.start_date,
            end_date=p.end_date,
            start_time=p.start_time,
            end_time=p.end_time,
            timezone=p.timezone,
            created_by=p.created_by,
        )
        for p in periods
    ]


@router.post("", response_model=LeaveRead, status_code=201)
async def create_leave(data: LeaveCreate, session: Session, user: CurrentUser) -> LeaveRead:
    period = await service.create(session, user, data)
    return (await _reads(session, [period]))[0]


@router.delete("/{period_id}", status_code=204)
async def delete_leave(period_id: uuid.UUID, session: Session, user: CurrentUser) -> Response:
    await service.remove(session, user, period_id)
    return Response(status_code=204)


@router.get("/mine", response_model=list[LeaveRead])
async def my_leave(session: Session, user: CurrentUser) -> list[LeaveRead]:
    return await _reads(session, await service.list_for_user(session, user.id))


@router.get("/users/{user_id}", response_model=list[LeaveRead])
async def user_leave(user_id: uuid.UUID, session: Session, user: CurrentUser) -> list[LeaveRead]:
    """One person's leave, for whoever may record it: themselves, a steward of a
    team they are on, an admin (RADD-1481)."""
    if not await service.may_manage_user(session, user, user_id):
        raise ForbiddenError("you can only see the leave of yourself or your team's members")
    return await _reads(session, await service.list_for_user(session, user_id))


@router.get("/teams", response_model=list[TeamLeaveRef])
async def stewarded_teams(session: Session, user: CurrentUser) -> list[TeamLeaveRef]:
    """The teams whose members' leave the caller may record (RADD-1481)."""
    teams = await service.stewarded_teams(session, user)
    return [TeamLeaveRef(id=team.id, name=team.name) for team in teams]


@router.get("/teams/{team_id}", response_model=TeamLeaveRead)
async def team_leave(
    team_id: uuid.UUID,
    session: Session,
    user: CurrentUser,
    since: Annotated[date | None, Query()] = None,
) -> TeamLeaveRead:
    """A team's members and their leave, for its stewards and admins (RADD-1481)."""
    team = await teams_service.get_team(session, team_id)
    if not await service.may_manage_team(session, user, team):
        raise ForbiddenError("a team's leave is visible to its owner, managers and admins")
    members = await teams_service.list_team_members(session, team_id)
    return TeamLeaveRead(
        team_id=team.id,
        team_name=team.name,
        members=[
            TeamLeaveMember(id=m.id, name=m.name, timezone=m.timezone)
            for m in sorted(members, key=lambda m: m.name.lower())
            if m.active
        ],
        periods=await _reads(session, await service.list_for_team(session, team_id, since=since)),
    )


@router.get("/holidays", response_model=list[LeaveRead])
async def holidays(session: Session, user: CurrentUser) -> list[LeaveRead]:
    """Team holidays, org-visible — knowing another region is off is the point."""
    return await _reads(session, await service.list_holidays(session))


@router.get("/current", response_model=list[CurrentLeave])
async def current(session: Session, user: CurrentUser) -> list[CurrentLeave]:
    """Everyone away NOW — the app-wide dim + icon indicator's one query."""
    return await service.current(session, datetime.now(UTC))


@router.get("/calendar", response_model=list[LeaveCalendarEntry])
async def calendar(
    start: date, end: date, session: Session, user: CurrentUser
) -> list[LeaveCalendarEntry]:
    """Absence spans overlapping [start, end], holidays pre-expanded per member
    (the timesheet joins these onto its day grid)."""
    return await service.calendar(session, start, end)
