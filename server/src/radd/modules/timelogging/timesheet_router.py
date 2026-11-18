"""Timesheet report endpoint — weekly/daily/monthly is a client-side pivot of these entries."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser
from radd.modules.settings import service as settings_service
from radd.modules.settings.types import SettingKey
from radd.modules.teams import service as teams_service

from . import mytickets, service, timesheet
from .slq.suggest import suggest_worklog
from .schemas import MyTicket, TeamRef, Timesheet, UserRef

router = APIRouter(prefix="/timesheet", tags=["timelogging"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=Timesheet)
async def get_timesheet(
    session: Session,
    user: CurrentUser,
    start: date,
    end: date,
    user_id: Annotated[list[uuid.UUID] | None, Query()] = None,
    team_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    q: str | None = None,
) -> Timesheet:
    if start > end:
        raise HTTPException(status_code=422, detail="start must be on or before end")
    await authz.require_member(session, user)  # the member floor (RADD-788)
    requested: set[uuid.UUID] | None = set(user_id) if user_id else None
    members = []
    if team_id is not None:
        members = await teams_service.list_team_members(session, team_id)
        member_ids = {m.id for m in members}
        requested = (requested & member_ids) if requested is not None else member_ids
    requested = await timesheet.visible_user_ids(session, user, requested)
    where = await service.compile_worklog_filter(session, user, q) if q and q.strip() else None
    sheet = await timesheet.build(
        session, start, end, actor=user, project_id=project_id, user_ids=requested, where=where
    )
    # Outlier-flag config rides on the payload — resolved server-side so the
    # grid and the settings can never disagree.
    sheet.day_min_hours = int(
        await settings_service.resolve(session, SettingKey.TIMESHEET_DAY_MIN_HOURS)
    )
    sheet.day_max_hours = int(
        await settings_service.resolve(session, SettingKey.TIMESHEET_DAY_MAX_HOURS)
    )
    week = str(await settings_service.resolve(session, SettingKey.WORK_WEEK_DAYS))
    sheet.work_days = [day.strip().lower() for day in week.split(",") if day.strip()]
    sheet.people = sorted(
        (UserRef(id=m.id, name=m.name) for m in members if requested is None or m.id in requested),
        key=lambda person: person.name.lower(),
    )
    sheet.hours_per_day = int(
        await settings_service.resolve(session, SettingKey.TIMELOG_HOURS_PER_DAY)
    )
    sheet.attention_low_percent = int(
        await settings_service.resolve(session, SettingKey.TIMESHEET_ATTENTION_LOW_PERCENT)
    )
    sheet.attention_high_percent = int(
        await settings_service.resolve(session, SettingKey.TIMESHEET_ATTENTION_HIGH_PERCENT)
    )
    sheet.attention_days_percent = int(
        await settings_service.resolve(session, SettingKey.TIMESHEET_ATTENTION_DAYS_PERCENT)
    )
    sheet.work_day_start_hour = min(
        23,
        max(0, int(await settings_service.resolve(session, SettingKey.TIMESHEET_WORK_DAY_START_HOUR))),
    )
    return sheet


@router.get("/teams", response_model=list[TeamRef])
async def reviewable_teams(session: Session, user: CurrentUser) -> list[TeamRef]:
    """The teams whose time the caller may review: every team with
    `timesheet.view`, otherwise the ones they own or manage (RADD-1576). Empty
    for anyone else, which is what keeps the Team view from being offered."""
    await authz.require_member(session, user)
    return [
        TeamRef(id=team.id, name=team.name)
        for team in await timesheet.reviewable_teams(session, user)
    ]


@router.get("/my-tickets", response_model=list[MyTicket])
async def my_tickets(session: Session, user: CurrentUser) -> list[MyTicket]:
    """The issues the caller is likely to log time on, most recent first: open
    and assigned to them, booked on lately, or acted on lately — each with why
    (RADD-1572). Bounded by what they can read."""
    await authz.require_member(session, user)
    return await mytickets.my_tickets(session, user)


_WORKLOG_SLQ_DOC = (
    "Worklog SLQ (spec 98): the timesheet's dialect, rooted at the WORKLOG so it can express "
    "general worklogs (`issue IS EMPTY`) and the author-vs-assignee split "
    "(`author = me AND issue.assignee != me`). `issue.<field>` delegates to the item dialect."
)


@router.get("/slq/validate", description=_WORKLOG_SLQ_DOC)
async def validate_worklog_slq(session: Session, user: CurrentUser, q: str = "") -> dict[str, bool]:
    """Parse + compile only, zero worklog I/O — the editor's per-keystroke check."""
    if q.strip():
        await service.compile_worklog_filter(session, user, q)
    return {"ok": True}


@router.get("/slq/suggest", description=_WORKLOG_SLQ_DOC)
async def suggest_worklog_slq(
    session: Session,
    user: CurrentUser,
    q: str = "",
    cursor: Annotated[int | None, Query(ge=0)] = None,
):
    return await suggest_worklog(session, actor=user, q=q, cursor=cursor)
