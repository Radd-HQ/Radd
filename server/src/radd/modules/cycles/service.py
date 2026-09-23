import uuid
from collections.abc import Iterable
from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, NotFoundError
from radd.modules.auth.models import User
from radd.kernel import changes
from radd.modules.events import service as events
from radd.clock import utcnow

from .history import (  # noqa: F401 — the items module's public seam (spec 56)
    past_cycles_by_item_ids,
    record_cycle_change,
)
from .models import Cycle, CycleSeries, CycleTeam, ItemCycleRecord
from .schemas import (
    CycleComplete,
    CycleCompleteResult,
    CycleCreate,
    CycleRead,
    CycleSeriesUpdate,
    CycleUpdate,
)
from .types import (
    CycleEntity,
    CycleEvent,
    CycleStatus,
    SeriesEvent,
    cycle_label,
    cycle_name,
    cycle_status,
    parse_cycle_name,
    same_label,
    series_draft_names,
    series_windows,
)

# Re-exported so consumers (items hydration/SLQ) touch only this service seam.
__all__ = [
    "active_cycles",
    "complete_cycle",
    "create_cycle",
    "cycle_status",
    "cycles_by_ids",
    "delete_cycle",
    "delete_series",
    "ensure_series_drafts",
    "get_cycle",
    "get_series",
    "list_cycles",
    "list_series",
    "recent_completed_cycles",
    "to_read",
    "update_cycle",
    "update_series",
]

# Fallback sprint length when starting a next cycle that has no dates and the
# closed one carried none either (a two-week sprint, inclusive dates).
DEFAULT_CYCLE_LENGTH = timedelta(days=13)


def _status(cycle: Cycle, today: date) -> CycleStatus:
    return cycle_status(cycle.start_date, cycle.end_date, today, cycle.completed_at)


def to_read(
    cycle: Cycle, today: date, team_ids: Iterable[uuid.UUID] = ()
) -> CycleRead:
    return CycleRead(
        id=cycle.id,
        name=cycle.name,
        start_date=cycle.start_date,
        end_date=cycle.end_date,
        goal=cycle.goal,
        status=_status(cycle, today),
        completed_at=cycle.completed_at,
        team_ids=list(team_ids),
        project_id=cycle.project_id,
        created_at=cycle.created_at,
        updated_at=cycle.updated_at,
    )


# --- team visibility (spec 60): no rows = public; rows = those teams only ---


def ids_by_status(statuses: list[str]):
    """Derived lifecycle query shared by Planning and SLQ; no date rules duplicated."""
    from datetime import date
    from .directory import status_expression

    return select(Cycle.id).where(status_expression(date.today()).in_(statuses))


def ids_by_names(names: list[str]):
    """Select of cycle ids matching these NAMES — the query-fragment seam the
    items SLQ `cycle` builtin composes into `WorkItem.cycle_id IN (…)`
    (RADD-888: the fragment crosses the boundary, the table does not)."""
    from sqlalchemy import select as _select

    return _select(Cycle.id).where(Cycle.name.in_(names))


def closed_stint_item_ids(names: list[str] | None = None):
    """Select of WORK-ITEM ids with a closed cycle stint (spec 56 carryover),
    optionally narrowed to stints in the named cycles — the whole `past_cycle`
    subquery, owned here because ItemCycleRecord is this module's table."""
    from sqlalchemy import select as _select

    stmt = _select(ItemCycleRecord.item_id).where(ItemCycleRecord.removed_at.is_not(None))
    if names is not None:
        stmt = stmt.join(Cycle, Cycle.id == ItemCycleRecord.cycle_id).where(Cycle.name.in_(names))
    return stmt


async def team_ids_by_cycle(
    session: AsyncSession, cycle_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, list[uuid.UUID]]:
    ids = set(cycle_ids)
    if not ids:
        return {}
    result = await session.execute(select(CycleTeam).where(CycleTeam.cycle_id.in_(ids)))
    by_cycle: dict[uuid.UUID, list[uuid.UUID]] = {}
    for row in result.scalars():
        by_cycle.setdefault(row.cycle_id, []).append(row.team_id)
    return by_cycle


async def set_cycle_teams(
    session: AsyncSession, cycle: Cycle, team_ids: Iterable[uuid.UUID]
) -> list[uuid.UUID]:
    """Full-replace the cycle's team associations ([] = public again)."""
    from radd.modules.teams import service as teams_service  # deferred: teams loads later

    valid = {team.id for team in await teams_service.list_teams(session)}
    unique = list(dict.fromkeys(team_ids))
    for team_id in unique:
        if team_id not in valid:
            raise ConflictError(CycleEntity.CYCLE, reason=f"unknown team {team_id}")
    await session.execute(delete(CycleTeam).where(CycleTeam.cycle_id == cycle.id))
    session.add_all(CycleTeam(cycle_id=cycle.id, team_id=team_id) for team_id in unique)
    await session.flush()
    return unique


async def visible_cycles(
    session: AsyncSession,
    user: User,
    *,
    status: CycleStatus | None = None,
    today: date | None = None,
) -> tuple[list[Cycle], dict[uuid.UUID, list[uuid.UUID]]]:
    """(cycles the user may see, team_ids per cycle). Cycle managers see every
    cycle; everyone else sees public cycles plus their own teams' (spec 60)."""
    from .directory import page

    rows, teams, _ = await page(session, user, status=status, today=today)
    return rows, teams


async def cycle_visible_to(session: AsyncSession, cycle: Cycle, user: User) -> bool:
    """Single-cycle visibility guard (the cycle page / stats endpoints — 404 when
    hidden, mirroring view sharing's don't-reveal-existence behavior)."""
    from radd.modules.auth import authz
    from radd.modules.teams import service as teams_service

    restricted = (await team_ids_by_cycle(session, [cycle.id])).get(cycle.id)
    if not restricted:
        return True
    perms = await authz.effective_permissions(session, user)
    if authz.Permission.GLOBAL_MANAGE in perms:  # admins; see visible_cycles
        return True
    my_teams = await teams_service.user_team_ids(session, user.id)
    return bool(set(my_teams) & set(restricted))


async def recent_completed_cycles(session: AsyncSession, *, actor: User | None, limit: int, today: date):
    """Public reporting seam: restrict visibility before choosing recent cycles."""
    from .directory import recent_completed

    return await recent_completed(session, actor=actor, limit=limit, today=today)


def _check_dates(start: date | None, end: date | None) -> None:
    # Only ordered when both are set; a missing date makes the cycle a DRAFT.
    if start is not None and end is not None and end < start:
        raise ConflictError(CycleEntity.CYCLE, reason="end_date must be on or after start_date")


async def create_cycle(
    session: AsyncSession, data: CycleCreate, today: date, actor_id: uuid.UUID | None = None
) -> CycleRead:
    _check_dates(data.start_date, data.end_date)
    name = data.name.strip()
    start_date, end_date = data.start_date, data.end_date
    if data.recurring:
        # "PIPE - 120" → label PIPE starting at 120; a bare "PIPE" starts at
        # `next_number` (import continuity: numbering can begin wherever Jira left off).
        parsed = parse_cycle_name(name)
        if parsed is not None:
            label, first = parsed
        else:
            label, first = name, data.next_number or 1
            name = cycle_name(label, first)
        series = await _upsert_series(
            session,
            label,
            data.drafts_ahead,
            first + 1,
            actor_id,
            start_weekday=data.start_weekday,
            duration_days=data.duration_days,
        )
        # A scheduled cadence + no explicit dates → the first cycle computes its own
        # timeline (chained after the label's latest scheduled cycle, else from today).
        if start_date is None and end_date is None and _is_scheduled(series):
            existing = await list_cycles(session)
            latest_end = max(
                (
                    c.end_date
                    for c in existing
                    if c.end_date is not None and same_label(cycle_label(c.name), label)
                ),
                default=None,
            )
            ((start_date, end_date),) = series_windows(
                latest_end, today, series.start_weekday, series.duration_days, 1
            )
    cycle = Cycle(
        name=name,
        start_date=start_date,
        end_date=end_date,
        goal=data.goal,
        project_id=data.project_id,
    )
    session.add(cycle)
    await session.flush()
    team_ids = await set_cycle_teams(session, cycle, data.team_ids) if data.team_ids else []
    await _emit(session, CycleEvent.CREATED, cycle, actor_id)
    series = await _series_for_label(session, cycle_label(name))
    if series is not None:
        await ensure_series_drafts(session, series, today, actor_id)
    return to_read(cycle, today, team_ids)


async def update_cycle(
    session: AsyncSession,
    cycle_id: uuid.UUID,
    data: CycleUpdate,
    today: date,
    actor_id: uuid.UUID | None = None,
) -> CycleRead:
    cycle = await get_cycle(session, cycle_id)
    before = await _cycle_audit_state(session, cycle)
    if data.name is not None:
        cycle.name = data.name
    # Dates use the model_fields_set idiom: omitted = unchanged, explicit null =
    # clear (scheduled -> draft). Name/goal have no "clear" (name is required).
    if "start_date" in data.model_fields_set:
        cycle.start_date = data.start_date
    if "end_date" in data.model_fields_set:
        cycle.end_date = data.end_date
    if data.goal is not None:
        cycle.goal = data.goal
    if "project_id" in data.model_fields_set:
        cycle.project_id = data.project_id
    _check_dates(cycle.start_date, cycle.end_date)
    if data.team_ids is not None:  # [] = make public again; omitted = unchanged
        team_ids = await set_cycle_teams(session, cycle, data.team_ids)
    else:
        team_ids = (await team_ids_by_cycle(session, [cycle.id])).get(cycle.id, [])
    await session.flush()
    await _emit(
        session,
        CycleEvent.UPDATED,
        cycle,
        actor_id,
        changes.diff(before, await _cycle_audit_state(session, cycle), collections=("teams",)),
    )
    return to_read(cycle, today, team_ids)


async def delete_cycle(
    session: AsyncSession, cycle_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> None:
    cycle = await get_cycle(session, cycle_id)
    # Items' cycle_id is nulled by the FK's ON DELETE SET NULL — no manual cleanup.
    await session.delete(cycle)
    await session.flush()
    await _emit(session, CycleEvent.DELETED, cycle, actor_id)
    # Deliberately NO ensure_drafts_ahead here: it would instantly recreate a
    # deleted draft under the same name, making drafts undeletable.


async def get_cycle(session: AsyncSession, cycle_id: uuid.UUID) -> Cycle:
    cycle = await session.get(Cycle, cycle_id)
    if cycle is None:
        raise NotFoundError(CycleEntity.CYCLE, cycle_id)
    return cycle


async def cycles_by_ids(
    session: AsyncSession, ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, Cycle]:
    result = await session.execute(select(Cycle).where(Cycle.id.in_(set(ids))))
    return {cycle.id: cycle for cycle in result.scalars()}


async def list_cycles(
    session: AsyncSession,
    *,
    status: CycleStatus | None = None,
    today: date | None = None,
) -> list[Cycle]:
    """All cycles, ordered by start date. `status` filters by the derived
    status (requires `today`, which the router passes as date.today())."""
    result = await session.execute(select(Cycle).order_by(Cycle.start_date))
    cycles = list(result.scalars())
    if status is not None:
        pivot = today or date.today()
        cycles = [c for c in cycles if _status(c, pivot) is status]
    return cycles


async def active_cycles(session: AsyncSession, today: date) -> list[Cycle]:
    """Cycles currently running (start_date <= today <= end_date, not
    explicitly closed early)."""
    result = await session.execute(
        select(Cycle)
        .where(
            Cycle.start_date <= today,
            Cycle.end_date >= today,
            Cycle.completed_at.is_(None),
        )
        .order_by(Cycle.start_date)
    )
    return list(result.scalars())


async def complete_cycle(
    session: AsyncSession,
    cycle_id: uuid.UUID,
    data: CycleComplete,
    today: date,
    actor: User,
) -> CycleCompleteResult:
    """The Jira "Complete sprint" flow: move open items to another cycle or the
    backlog, stamp the close, optionally start the target, then top up drafts."""
    # Deferred: items imports this module's service (hydration/SLQ), so the reverse
    # edge must resolve at call time — same pattern as projects→settings (spec 50).
    from radd.modules.items import service as items_service

    cycle = await get_cycle(session, cycle_id)
    if not await cycle_visible_to(session, cycle, actor):
        raise NotFoundError(CycleEntity.CYCLE, cycle.id)
    if _status(cycle, today) is CycleStatus.COMPLETED:
        raise ConflictError(CycleEntity.CYCLE, reason="cycle is already completed")

    target: Cycle | None = None
    if data.move_open_to is not None:
        target = await get_cycle(session, data.move_open_to)
        if not await cycle_visible_to(session, target, actor):
            raise NotFoundError(CycleEntity.CYCLE, target.id)
        if target.id == cycle.id:
            raise ConflictError(
                CycleEntity.CYCLE, reason="cannot move items into the cycle being completed"
            )
        if _status(target, today) is CycleStatus.COMPLETED:
            raise ConflictError(CycleEntity.CYCLE, reason="target cycle is completed")

    moved = await items_service.move_open_cycle_items(
        session, cycle.id, target.id if target else None, actor
    )
    cycle.completed_at = utcnow()
    await session.flush()
    await _emit(session, CycleEvent.COMPLETED, cycle, actor.id)

    if target is not None and data.start_next:
        target_before = await _cycle_audit_state(session, target)
        if target.start_date is None or target.start_date > today:
            target.start_date = today
        if target.end_date is None or target.end_date < target.start_date:
            length = (
                cycle.end_date - cycle.start_date
                if cycle.start_date is not None and cycle.end_date is not None
                else DEFAULT_CYCLE_LENGTH
            )
            target.end_date = target.start_date + length
        await session.flush()
        await _emit(
            session,
            CycleEvent.UPDATED,
            target,
            actor.id,
            changes.diff(target_before, await _cycle_audit_state(session, target)),
        )

    series = await _series_for_label(session, cycle_label(cycle.name))
    provisioned = (
        await ensure_series_drafts(session, series, today, actor.id) if series else []
    )
    return CycleCompleteResult(
        cycle=to_read(cycle, today),
        moved_count=moved,
        next_cycle=to_read(target, today) if target is not None else None,
        provisioned=provisioned,
    )


# --- recurring series (per-label auto-provisioning) ---


async def list_series(session: AsyncSession) -> list[CycleSeries]:
    result = await session.execute(select(CycleSeries).order_by(CycleSeries.label))
    return list(result.scalars())


async def get_series(session: AsyncSession, series_id: uuid.UUID) -> CycleSeries:
    series = await session.get(CycleSeries, series_id)
    if series is None:
        raise NotFoundError(CycleEntity.SERIES, series_id)
    return series


async def _series_for_label(
    session: AsyncSession, label: str | None
) -> CycleSeries | None:
    if label is None:
        return None
    for series in await list_series(session):
        if same_label(series.label, label):
            return series
    return None


def _is_scheduled(series: CycleSeries) -> bool:
    return series.start_weekday is not None and series.duration_days is not None


def _check_schedule(start_weekday: int | None, duration_days: int | None) -> None:
    if (start_weekday is None) != (duration_days is None):
        raise ConflictError(
            CycleEntity.SERIES, reason="set both start_weekday and duration_days, or neither"
        )


async def _upsert_series(
    session: AsyncSession,
    label: str,
    drafts_ahead: int,
    next_number: int,
    actor_id: uuid.UUID | None,
    *,
    start_weekday: int | None = None,
    duration_days: int | None = None,
) -> CycleSeries:
    _check_schedule(start_weekday, duration_days)
    series = await _series_for_label(session, label)
    if series is None:
        series = CycleSeries(
            label=label,
            drafts_ahead=drafts_ahead,
            next_number=next_number,
            start_weekday=start_weekday,
            duration_days=duration_days,
        )
        session.add(series)
        await session.flush()
        await _emit_series(session, SeriesEvent.CREATED, series, actor_id)
        return series
    series.drafts_ahead = drafts_ahead
    series.next_number = max(series.next_number, next_number)
    if start_weekday is not None:  # re-registering may refine the cadence, never clear it
        series.start_weekday = start_weekday
        series.duration_days = duration_days
    await session.flush()
    await _emit_series(session, SeriesEvent.UPDATED, series, actor_id)
    return series


async def update_series(
    session: AsyncSession,
    series_id: uuid.UUID,
    data: CycleSeriesUpdate,
    today: date,
    actor_id: uuid.UUID | None = None,
) -> CycleSeries:
    series = await get_series(session, series_id)
    before = changes.snapshot(series, SERIES_FIELDS)
    if data.drafts_ahead is not None:
        series.drafts_ahead = data.drafts_ahead
    if data.next_number is not None:
        series.next_number = data.next_number
    # Cadence uses the model_fields_set idiom: omitted = unchanged, explicit null clears.
    if "start_weekday" in data.model_fields_set:
        series.start_weekday = data.start_weekday
    if "duration_days" in data.model_fields_set:
        series.duration_days = data.duration_days
    _check_schedule(series.start_weekday, series.duration_days)
    await session.flush()
    await _emit_series(
        session, SeriesEvent.UPDATED, series, actor_id, changes.diff_object(series, before)
    )
    # Raising the look-ahead / setting a cadence provisions + schedules immediately.
    await ensure_series_drafts(session, series, today, actor_id)
    return series


async def delete_series(
    session: AsyncSession, series_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> None:
    """Stop recurring — existing cycles keep their names, nothing else changes."""
    series = await get_series(session, series_id)
    await session.delete(series)
    await session.flush()
    await _emit_series(session, SeriesEvent.DELETED, series, actor_id)


async def ensure_series_drafts(
    session: AsyncSession,
    series: CycleSeries,
    today: date,
    actor_id: uuid.UUID | None,
) -> list[str]:
    """Top up the series to `drafts_ahead` future cycles, numbered from `next_number`
    (skipping names an import already took). With a cadence configured, every
    provisioned cycle gets its timeline (windows chained after the label's latest
    scheduled cycle, starts snapped to the weekday) — and any EXISTING dateless
    drafts of the label are scheduled first, in number order. Returns names created."""
    cycles = await list_cycles(session)
    mine = [c for c in cycles if same_label(cycle_label(c.name), series.label)]
    scheduled = _is_scheduled(series)
    future = sum(
        1 for c in mine if _status(c, today) in (CycleStatus.DRAFT, CycleStatus.UPCOMING)
    )
    missing = max(0, series.drafts_ahead - future)

    dateless: list[Cycle] = []
    windows: list[tuple[date, date]] = []
    if scheduled:
        dateless = sorted(
            (
                c
                for c in mine
                if c.start_date is None and c.end_date is None and c.completed_at is None
            ),
            key=lambda c: (parse_cycle_name(c.name) or (c.name, 0))[1],
        )
        latest_end = max((c.end_date for c in mine if c.end_date is not None), default=None)
        windows = series_windows(
            latest_end,
            today,
            series.start_weekday,  # type: ignore[arg-type]  # _is_scheduled guards
            series.duration_days,  # type: ignore[arg-type]
            len(dateless) + missing,
        )
        for cycle, (start, end) in zip(dateless, windows):
            cycle.start_date, cycle.end_date = start, end
            await session.flush()
            await _emit(session, CycleEvent.UPDATED, cycle, actor_id)

    if missing <= 0:
        return []
    names, next_number = series_draft_names(
        (c.name for c in cycles), series.label, series.next_number, missing
    )
    new_windows = windows[len(dateless) :] if scheduled else [None] * missing
    for name, window in zip(names, new_windows):
        draft = Cycle(
            name=name,
            start_date=window[0] if window else None,
            end_date=window[1] if window else None,
            # RADD-1291: a series' drafts belong where its latest cycle does.
            project_id=max(mine, key=lambda c: (c.created_at is not None, c.created_at)).project_id if mine else None,
        )
        session.add(draft)
        await session.flush()
        await _emit(session, CycleEvent.CREATED, draft, actor_id)
    series.next_number = next_number
    await session.flush()
    return names


#: What a series edit can touch — and therefore what its diff mentions.
SERIES_FIELDS: tuple[str, ...] = ("drafts_ahead", "next_number", "start_weekday", "duration_days")


async def _cycle_audit_state(session: AsyncSession, cycle: Cycle) -> dict:
    """What a cycle diff can mention (spec 123): team NAMES, not ids."""
    from radd.modules.teams import service as teams_service  # deferred: teams loads later

    team_ids = (await team_ids_by_cycle(session, [cycle.id])).get(cycle.id, [])
    found = await teams_service.teams_by_ids(session, team_ids)
    return {
        "name": cycle.name,
        "start_date": cycle.start_date,
        "end_date": cycle.end_date,
        "goal": cycle.goal,
        "teams": sorted(found[t].name if t in found else str(t) for t in team_ids),
        "project": str(cycle.project_id) if cycle.project_id else None,
    }


async def _emit_series(
    session: AsyncSession,
    event_type: SeriesEvent,
    series: CycleSeries,
    actor_id: uuid.UUID | None,
    diff: list[dict] | None = None,
) -> None:
    await events.emit(
        session,
        event_type=event_type,
        entity_type=CycleEntity.SERIES,
        entity_id=series.id,
        actor_id=actor_id,
        payload={
            "label": series.label,
            "drafts_ahead": series.drafts_ahead,
            "next_number": series.next_number,
        },
        changes=diff,
    )


async def _emit(
    session: AsyncSession,
    event_type: CycleEvent,
    cycle: Cycle,
    actor_id: uuid.UUID | None,
    diff: list[dict] | None = None,
) -> None:
    await events.emit(
        session,
        event_type=event_type,
        entity_type=CycleEntity.CYCLE,
        entity_id=cycle.id,
        actor_id=actor_id,
        payload={
            "name": cycle.name,
            "start_date": cycle.start_date.isoformat() if cycle.start_date else None,
            "end_date": cycle.end_date.isoformat() if cycle.end_date else None,
        },
        changes=diff,
    )
