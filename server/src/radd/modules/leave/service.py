"""Leave + team holidays (spec 104; hours and stewardship UI in RADD-1481).

Authz (user decision): everyone records their OWN leave; a team steward
(owner/manager) records leave for their team's members; instance admins record
anyone's leave and define team HOLIDAYS. No approval flow — an entry is a
statement of absence, not a request.

Time. A period is inclusive calendar days in the subject's own calendar, and an
optional wall-clock time at either end narrows the boundary day (RADD-1481). The
row names the zone those are read in, resolved once at creation — the request's,
else the subject's profile zone, else the actor's, else UTC — so a later profile
change never moves recorded leave. "Away now" is answered per row in its zone;
the calendar and the sockets stay date-granular, which is what their consumers
(the timesheet grid, round-robin by day, the SLA clock) ask for.
"""

import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, ForbiddenError, NotFoundError
from radd.modules.auth import authz
from radd.modules.auth import service as auth_service
from radd.modules.auth.models import User
from radd.modules.events import service as events
from radd.modules.teams import service as teams_service
from radd.modules.teams.models import Team

from .models import LeavePeriod
from .schemas import CurrentLeave, LeaveCalendarEntry, LeaveCreate
from .types import LeaveEntity, LeaveEvent, LeaveKind

#: What a row with no zone (pre-RADD-1481) is read in.
DEFAULT_ZONE = "UTC"


async def may_manage_user(session: AsyncSession, actor: User, user_id: uuid.UUID) -> bool:
    if getattr(actor, "token_scope", None) is not None:
        return False
    if actor.id == user_id or authz.is_instance_admin(actor):
        return True
    # A steward (owner/manager) of any team the subject belongs to may cover
    # for them — the "forgot to log their vacation" case.
    for team in await teams_service.teams_for_user(session, user_id):
        if await teams_service.is_team_steward(session, actor.id, team):
            return True
    return False


async def may_manage_team(session: AsyncSession, actor: User, team: Team) -> bool:
    """May this actor see and record the leave of THIS team's members?"""
    if getattr(actor, "token_scope", None) is not None:
        return False
    return authz.is_instance_admin(actor) or await teams_service.is_team_steward(
        session, actor.id, team
    )


async def _authorize(session: AsyncSession, actor: User, period: LeavePeriod) -> None:
    if getattr(actor, "token_scope", None) is not None:
        raise ForbiddenError("leave changes require an account session or a full-access key")
    if period.team_id is not None:
        if not authz.is_instance_admin(actor):
            raise ForbiddenError("team holidays are managed by instance admins")
        return
    assert period.user_id is not None
    if not await may_manage_user(session, actor, period.user_id):
        raise ForbiddenError("you can only record leave for yourself or your team's members")


def _ordered(data: LeaveCreate) -> bool:
    if data.start_date != data.end_date:
        return data.start_date < data.end_date
    if data.start_time is None or data.end_time is None:
        return True
    return data.start_time < data.end_time


def zone_of(name: str) -> ZoneInfo:
    return ZoneInfo(name or DEFAULT_ZONE)


async def _resolve_timezone(
    session: AsyncSession, requested: str | None, subject_id: uuid.UUID | None, actor: User
) -> str:
    """The zone a new row's dates and times are read in: request → subject's
    profile → actor's profile → UTC. Named explicitly on the row, so the UI can
    show it and a later profile change never shifts recorded leave."""
    name = (requested or "").strip()
    if name:
        try:
            ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            raise ConflictError(LeaveEntity.LEAVE, reason=f"unknown time zone {name!r}") from None
        return name
    if subject_id is not None and subject_id != actor.id:
        subject = await auth_service.get_user(session, subject_id)
        if subject.timezone:
            return subject.timezone
    return actor.timezone or DEFAULT_ZONE


async def create(session: AsyncSession, actor: User, data: LeaveCreate) -> LeavePeriod:
    if data.user_id is not None and data.team_id is not None:
        raise ConflictError(LeaveEntity.LEAVE, reason="name a user OR a team, not both")
    # Neither subject named = the caller's own leave.
    user_id = data.user_id if data.team_id is None else None
    if data.team_id is None and user_id is None:
        user_id = actor.id
    if not _ordered(data):
        raise ConflictError(LeaveEntity.LEAVE, reason="the leave must end after it starts")
    if data.team_id is not None:
        if data.start_time is not None or data.end_time is not None:
            raise ConflictError(
                LeaveEntity.LEAVE, reason="a holiday is a whole day — times belong to personal leave"
            )
        await teams_service.get_team(session, data.team_id)  # 404 before authz
    period = LeavePeriod(
        user_id=user_id,
        team_id=data.team_id,
        kind=(LeaveKind.HOLIDAY if data.team_id is not None else LeaveKind.LEAVE).value,
        label=data.label.strip(),
        start_date=data.start_date,
        end_date=data.end_date,
        start_time=data.start_time,
        end_time=data.end_time,
        timezone=await _resolve_timezone(session, data.timezone, user_id, actor),
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
        # RADD-1320: WHO is away, as refs the automation walk can act on.
        subjects={"user": period.user_id, "team": period.team_id},
        payload={
            "user_id": str(period.user_id) if period.user_id else None,
            "team_id": str(period.team_id) if period.team_id else None,
            **_span_payload(period),
        },
    )
    return period


def _span_payload(period: LeavePeriod) -> dict:
    return {
        "kind": period.kind,
        "label": period.label,
        "start_date": period.start_date.isoformat(),
        "end_date": period.end_date.isoformat(),
        "start_time": period.start_time.isoformat() if period.start_time else None,
        "end_time": period.end_time.isoformat() if period.end_time else None,
        "timezone": period.timezone,
    }


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
        # RADD-1320: it named nobody at all — "whose leave went" was unanswerable.
        subjects={"user": period.user_id, "team": period.team_id},
        payload=_span_payload(period),
    )


async def list_for_user(session: AsyncSession, user_id: uuid.UUID) -> list[LeavePeriod]:
    result = await session.execute(
        select(LeavePeriod)
        .where(LeavePeriod.user_id == user_id)
        .order_by(LeavePeriod.start_date.desc(), LeavePeriod.start_time.desc().nulls_last())
    )
    return list(result.scalars())


async def list_for_team(
    session: AsyncSession, team_id: uuid.UUID, *, since: date | None = None
) -> list[LeavePeriod]:
    """The personal leave of a team's CURRENT members (RADD-1481), newest first;
    `since` drops rows that ended before it. Holidays are listed elsewhere."""
    members = await teams_service.list_team_members(session, team_id)
    if not members:
        return []
    query = select(LeavePeriod).where(LeavePeriod.user_id.in_([m.id for m in members]))
    if since is not None:
        query = query.where(LeavePeriod.end_date >= since)
    result = await session.execute(
        query.order_by(LeavePeriod.start_date.desc(), LeavePeriod.start_time.desc().nulls_last())
    )
    return list(result.scalars())


async def stewarded_teams(session: AsyncSession, actor: User) -> list[Team]:
    """The teams whose members' leave this actor may record: every team for an
    admin, the owned/managed ones for a steward, none for a scoped key."""
    if getattr(actor, "token_scope", None) is not None:
        return []
    if authz.is_instance_admin(actor):
        return await teams_service.list_teams(session)
    return await teams_service.stewarded_teams(session, actor.id)


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


async def _subjects(session: AsyncSession, period: LeavePeriod) -> list[uuid.UUID]:
    """The people a row marks away: the user, or a holiday's CURRENT members."""
    if period.user_id is not None:
        return [period.user_id]
    assert period.team_id is not None
    members = await teams_service.list_team_members(session, period.team_id)
    return [member.id for member in members]


def span(period: LeavePeriod) -> tuple[datetime, datetime]:
    """The row as a half-open instant interval [start, end) in its own zone:
    the start of the first day (or `start_time`) to the end of the last day
    (or `end_time`). Wall clock → instant through ZoneInfo, so DST is honored."""
    zone = zone_of(period.timezone)
    start = datetime.combine(period.start_date, period.start_time or time.min, tzinfo=zone)
    if period.end_time is None:
        end = datetime.combine(period.end_date + timedelta(days=1), time.min, tzinfo=zone)
    else:
        end = datetime.combine(period.end_date, period.end_time, tzinfo=zone)
    return start, end


async def calendar(
    session: AsyncSession, start: date, end: date
) -> list[LeaveCalendarEntry]:
    """Every user-absence span overlapping [start, end] — team holidays
    expanded to their CURRENT members, so consumers never join membership.
    Org-visible by design: absence presence is what the indicators exist for."""
    entries: list[LeaveCalendarEntry] = []
    for period in await _overlapping(session, start, end):
        entries.extend(
            LeaveCalendarEntry(
                user_id=user_id,
                kind=period.kind,
                label=period.label,
                start_date=period.start_date,
                end_date=period.end_date,
                start_time=period.start_time,
                end_time=period.end_time,
                timezone=period.timezone,
            )
            for user_id in await _subjects(session, period)
        )
    return entries


async def holiday_dates(session: AsyncSession, start: date, end: date) -> set[date]:
    """Every date in [start, end] a HOLIDAY covers (RADD-1031) — the SLA clock's
    non-working days. Holidays only (an item's timer has no person to be absent),
    and team-scoped rows count instance-wide: a clock has no subject to resolve a
    team against, unlike `calendar()`. Per-desk clocks would need a per-project
    calendar, not a filter here."""
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


async def current(session: AsyncSession, now: datetime) -> list[CurrentLeave]:
    """Who is away at the instant `now`, with the latest end per user — the
    app-wide dim + icon indicator renders from exactly this. Each row is judged
    in its own zone (RADD-1481): a 16:00 start is away at 16:30 local, not at
    11:00; an all-day row covers the subject's local day, not the server's."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    # A local calendar date lies within a day of the UTC date on either side.
    utc_day = now.astimezone(UTC).date()
    best: dict[uuid.UUID, tuple[datetime, CurrentLeave]] = {}
    for period in await _overlapping(session, utc_day - timedelta(days=1), utc_day + timedelta(days=1)):
        start, end = span(period)
        if not (start <= now < end):
            continue
        for user_id in await _subjects(session, period):
            existing = best.get(user_id)
            if existing is None or end > existing[0]:
                best[user_id] = (
                    end,
                    CurrentLeave(
                        user_id=user_id,
                        kind=period.kind,
                        label=period.label,
                        until=period.end_date,
                        until_time=period.end_time,
                        timezone=period.timezone,
                    ),
                )
    return [entry for _, entry in best.values()]


__all__ = [
    "calendar",
    "create",
    "current",
    "holiday_dates",
    "list_for_team",
    "list_for_user",
    "list_holidays",
    "may_manage_team",
    "may_manage_user",
    "remove",
    "span",
    "stewarded_teams",
    "zone_of",
]
