"""Timesheet report endpoint — weekly/daily/monthly is a client-side pivot of these entries."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser
from radd.modules.items import service as items_service
from radd.modules.settings import service as settings_service
from radd.modules.settings.types import SettingKey
from radd.modules.teams import service as teams_service

from . import service, timesheet
from .slq import compile_worklog_query, parse
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
    # Member floor (RADD-788). Seeing OTHER people's time stays a global
    # authority — holding timesheet.view on one project must not expose the
    # whole instance's hours — so that check is unchanged.
    await authz.require_member(session, user)
    can_view_all = (
        authz.Permission.TIMESHEET_VIEW in await authz.effective_permissions(session, user)
    )

    requested: set[uuid.UUID] | None = set(user_id) if user_id else None
    if team_id is not None:
        members = await teams_service.list_team_members(session, team_id)
        member_ids = {m.id for m in members}
        requested = (requested & member_ids) if requested is not None else member_ids
    if not can_view_all:
        # Without timesheet.view you only ever see your own logged time.
        requested = {user.id} if requested is None else (requested & {user.id})

    # `q` is the worklog SLQ (spec 98). Compiled here and ANDed onto the scope
    # filters inside build(), so it can only narrow what this actor may already
    # see — the visibility rules above are not something a query can reach past.
    where = None
    if q and q.strip():
        # Reuse the module's own resolver so `1d` means on the query what it
        # means on every worklog row.
        hours_per_day = await service._hours_per_day(session)
        where = (
            await compile_worklog_query(
                session,
                parse(q),
                current_user_id=user.id,
                hours_per_day=hours_per_day,
                denied_item_fields=await items_service.denied_slq_fields(session, user, None),
            )
        ).where

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
        hours_per_day = await service._hours_per_day(session)
        await compile_worklog_query(
            session,
            parse(q),
            current_user_id=user.id,
            hours_per_day=hours_per_day,
            denied_item_fields=await items_service.denied_slq_fields(session, user, None),
        )
    return {"ok": True}


@router.get("/slq/suggest", description=_WORKLOG_SLQ_DOC)
async def suggest_worklog_slq(
    session: Session,
    user: CurrentUser,
    q: str = "",
    cursor: Annotated[int | None, Query(ge=0)] = None,
):
    return await suggest_worklog(session, actor=user, q=q, cursor=cursor)
