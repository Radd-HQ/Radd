"""Leave + team holidays (spec: timesheet wave).

Authz (user decision): everyone records their OWN leave; a team steward
(owner/manager) records leave for their team's members; instance admins record
anyone's leave and define team HOLIDAYS. No approval flow — an entry is a
statement of absence, not a request.
"""

import uuid
from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth import authz
from radd.exceptions import ConflictError, ForbiddenError, NotFoundError
from radd.modules.auth.models import User
from radd.modules.events import service as events
from radd.modules.teams import service as teams_service

from .models import LeavePeriod
from .schemas import CurrentLeave, LeaveCalendarEntry, LeaveCreate
from .types import LeaveEntity, LeaveEvent, LeaveKind


def _is_admin(actor: User) -> bool:
    return authz.is_instance_admin(actor)


async def may_manage_user(session: AsyncSession, actor: User, user_id: uuid.UUID) -> bool:
    if getattr(actor, "token_scope", None) is not None:
        return False
    if actor.id == user_id or _is_admin(actor):
        return True
    # A steward (owner/manager) of any team the subject belongs to may cover
    # for them — the "forgot to log their vacation" case.
    for team in await teams_service.teams_for_user(session, user_id):
        if await teams_service.is_team_steward(session, actor.id, team):
            return True
    return False


async def _authorize(session: AsyncSession, actor: User, period: LeavePeriod) -> None:
    if getattr(actor, "token_scope", None) is not None:
        raise ForbiddenError("leave changes require an account session or a full-access key")
    if period.team_id is not None:
        if not _is_admin(actor):
            raise ForbiddenError("team holidays are managed by instance admins")
        return
    assert period.user_id is not None
    if not await may_manage_user(session, actor, period.user_id):
        raise ForbiddenError("you can only record leave for yourself or your team's members")


async def create(session: AsyncSession, actor: User, data: LeaveCreate) -> LeavePeriod:
    if data.user_id is not None and data.team_id is not None:
        raise ConflictError(LeaveEntity.LEAVE, reason="name a user OR a team, not both")
    # Neither subject named = the caller's own leave.
    user_id = data.user_id if data.team_id is None else None
    if data.team_id is None and user_id is None:
        user_id = actor.id
    if data.end_date < data.start_date:
        raise ConflictError(LeaveEntity.LEAVE, reason="end_date must be on or after start_date")
    if data.team_id is not None:
        await teams_service.get_team(session, data.team_id)  # 404 before authz
    period = LeavePeriod(
        user_id=user_id,
        team_id=data.team_id,
        kind=(LeaveKind.HOLIDAY if data.team_id is not None else LeaveKind.LEAVE).value,
        label=data.label.strip(),
        start_date=data.start_date,
        end_date=data.end_date,
        created_by=actor.id,
    )
    await _authorize(session, actor, period)
    session.add(period)
    await session.flush()
    await events.emit(
        session,
        event_type=LeaveEvent.CREATED,
        entity_type=LeaveEntity.LEAVE,
        entity_id=period.id,
        actor_id=actor.id,
        payload={
            "user_id": str(period.user_id) if period.user_id else None,
            "team_id": str(period.team_id) if period.team_id else None,
            "kind": period.kind,
            "label": period.label,
            "start_date": period.start_date.isoformat(),
            "end_date": period.end_date.isoformat(),
        },
    )
    return period


async def remove(session: AsyncSession, actor: User, period_id: uuid.UUID) -> None:
    period = await session.get(LeavePeriod, period_id)
    if period is None:
        raise NotFoundError(LeaveEntity.LEAVE, period_id)
    await _authorize(session, actor, period)
    await session.execute(delete(LeavePeriod).where(LeavePeriod.id == period.id))
    await events.emit(
        session,
        event_type=LeaveEvent.DELETED,
        entity_type=LeaveEntity.LEAVE,
        entity_id=period_id,
        actor_id=actor.id,
        payload={"kind": period.kind, "label": period.label},
    )


async def list_for_user(session: AsyncSession, user_id: uuid.UUID) -> list[LeavePeriod]:
    result = await session.execute(
        select(LeavePeriod)
        .where(LeavePeriod.user_id == user_id)
        .order_by(LeavePeriod.start_date.desc())
    )
    return list(result.scalars())


async def list_holidays(session: AsyncSession) -> list[LeavePeriod]:
    result = await session.execute(
        select(LeavePeriod)
        .where(LeavePeriod.team_id.is_not(None))
        .order_by(LeavePeriod.start_date.desc())
    )
    return list(result.scalars())


async def _overlapping(
    session: AsyncSession, start: date, end: date
) -> list[LeavePeriod]:
    result = await session.execute(
        select(LeavePeriod).where(
            LeavePeriod.start_date <= end, LeavePeriod.end_date >= start
        )
    )
    return list(result.scalars())


async def calendar(
    session: AsyncSession, start: date, end: date
) -> list[LeaveCalendarEntry]:
    """Every user-absence span overlapping [start, end] — team holidays
    expanded to their CURRENT members, so consumers never join membership.
    Org-visible by design: absence presence is what the indicators exist for."""
    entries: list[LeaveCalendarEntry] = []
    for period in await _overlapping(session, start, end):
        if period.user_id is not None:
            entries.append(
                LeaveCalendarEntry(
                    user_id=period.user_id,
                    kind=period.kind,
                    label=period.label,
                    start_date=period.start_date,
                    end_date=period.end_date,
                )
            )
            continue
        assert period.team_id is not None
        for member in await teams_service.list_team_members(session, period.team_id):
            entries.append(
                LeaveCalendarEntry(
                    user_id=member.id,
                    kind=period.kind,
                    label=period.label,
                    start_date=period.start_date,
                    end_date=period.end_date,
                )
            )
    return entries


async def holiday_dates(session: AsyncSession, start: date, end: date) -> set[date]:
    """Every date in [start, end] a HOLIDAY period covers (RADD-1031).

    Holidays only, never personal leave: a holiday is a day the studio is shut,
    which is a property of the calendar, while one person's absence is a
    property of that person. The distinction matters because this feeds the SLA
    clock (through the kernel's non-working-days socket) and an item's timer has
    no person to be absent.

    Team-scoped rows are read as instance-wide here, unlike `calendar()`, which
    expands them to members. That is not sloppiness but the same rule applied to
    a different subject: `calendar()` answers "who is away", so it needs the
    membership; a clock has no subject to resolve a team against, so any
    declared shutdown stops it. A regionally-split instance that wants
    per-desk clocks needs a per-project calendar — a bigger design than a filter
    here could fake.
    """
    dates: set[date] = set()
    result = await session.execute(
        select(LeavePeriod).where(
            LeavePeriod.kind == LeaveKind.HOLIDAY.value,
            LeavePeriod.start_date <= end,
            LeavePeriod.end_date >= start,
        )
    )
    for period in result.scalars():
        day = max(period.start_date, start)
        last = min(period.end_date, end)
        while day <= last:
            dates.add(day)
            day += timedelta(days=1)
    return dates


async def current(session: AsyncSession, today: date) -> list[CurrentLeave]:
    """Who is away TODAY, with the latest end date per user — the app-wide
    dim + icon indicator renders from exactly this."""
    best: dict[uuid.UUID, CurrentLeave] = {}
    for entry in await calendar(session, today, today):
        existing = best.get(entry.user_id)
        if existing is None or entry.end_date > existing.until:
            best[entry.user_id] = CurrentLeave(
                user_id=entry.user_id,
                kind=entry.kind,
                label=entry.label,
                until=entry.end_date,
            )
    return list(best.values())


__all__ = [
    "calendar",
    "create",
    "current",
    "holiday_dates",
    "list_for_user",
    "list_holidays",
    "may_manage_user",
    "remove",
]
