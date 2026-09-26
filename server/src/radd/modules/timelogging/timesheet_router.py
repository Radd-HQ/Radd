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

from . import service, timesheet
from .slq.suggest import suggest_worklog
from .schemas import Timesheet

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
    return sheet



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
