"""Read-only analytics folded on the fly over the reconstructed item timelines
(spec 16). `bucket_start(s)`, `matching_ids` and `report_scope` are public so a
plugin's own report (the SLA report in `slas`, RADD-1386) folds the same way."""

import statistics
import uuid
from datetime import date, datetime, time, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, NotFoundError
from radd.modules.auth import authz
from radd.modules.auth.models import User
from radd.modules.cycles import service as cycles_service
from radd.modules.cycles.types import CycleEntity
from radd.modules.items import bulk as items_bulk
from radd.modules.items import service as items_service
from radd.modules.items.enums import ItemKind
from radd.modules.workflow.types import StateCategory

from . import timeline
from .schemas import (
    BurnupPoint,
    BurnupSeries,
    CumulativeFlowBucket,
    CycleBrief,
    CycleWindow,
    ReportScope,
    ThroughputBucket,
    TimeInStateRow,
    VelocityReport,
    VelocityRow,
)
from .types import ReportInterval, ReportMeasure

DEFAULT_WINDOW_DAYS = 30


# --- bucketing — public: a plugin's own report buckets the same way (RADD-1386) ---


def bucket_start(day: date, interval: ReportInterval) -> date:
    """The date that labels `day`'s bucket (the Monday of its week, or the day itself)."""
    if interval is ReportInterval.WEEK:
        return day - timedelta(days=day.weekday())
    return day


def bucket_starts(start: date, end: date, interval: ReportInterval) -> list[date]:
    step = timedelta(weeks=1) if interval is ReportInterval.WEEK else timedelta(days=1)
    cursor = bucket_start(start, interval)
    buckets: list[date] = []
    while cursor <= end:
        buckets.append(cursor)
        cursor += step
    return buckets


def _end_of(day: date) -> datetime:
    """The instant just past midnight after `day` — used as an end-of-day snapshot point."""
    return datetime.combine(day + timedelta(days=1), time.min)


# --- the dashboard-wide SLQ filter seam ------------------------------------
# SLQ evaluates an item's state TODAY: `assignee = me` reports the history of the
# items assigned to me NOW. An uncompilable q raises SlqError -> the usual 422.


async def matching_ids(
    session: AsyncSession,
    actor: User | None,
    q: str | None,
    project_id: uuid.UUID | None = None,
    candidate_ids: list[uuid.UUID] | None = None,
) -> set[uuid.UUID] | None:
    """The item ids a report may range over: visibility ALWAYS applied (omitting
    `q` must not skip it, RADD-789), the SLQ intersected on top — the rule
    `GET /items` follows. None = no actor, unfiltered."""
    if actor is None:
        return None
    return await items_bulk.visible_matching_ids(
        session, actor=actor, q=(q or "").strip() or None, project_id=project_id,
        candidate_ids=candidate_ids,
    )


async def report_scope(session: AsyncSession, actor: User | None) -> ReportScope:
    """What a cross-project figure was computed over, for the header (RADD-789)."""
    from radd.modules.projects import service as projects_service

    projects = await projects_service.list_projects(session)
    if actor is None:
        return ReportScope(covered=sorted(p.key for p in projects), total=len(projects))
    readable = await authz.readable_projects(session, actor)
    return ReportScope(
        covered=sorted(p.key for p in projects if p.id in readable), total=len(projects)
    )


def _keep(item_ids: list[uuid.UUID], matches: set[uuid.UUID] | None) -> list[uuid.UUID]:
    if matches is None:
        return item_ids
    return [item_id for item_id in item_ids if item_id in matches]


async def _project_timelines(session: AsyncSession, project_id, actor: User | None, q: str | None):
    matches = await matching_ids(session, actor, q, project_id)
    item_ids = _keep(await timeline.item_ids_for_project(session, project_id), matches)
    return await timeline.build_item_timelines(session, item_ids)


async def _cycle_timelines(session: AsyncSession, cycle_id, actor: User | None, q: str | None):
    """(the cycle's visible, q-matching item ids, their timelines)."""
    candidates = await timeline.item_ids_for_cycle(session, cycle_id)
    matches = await matching_ids(session, actor, q, candidate_ids=candidates)
    item_ids = _keep(candidates, matches)
    return item_ids, await timeline.build_item_timelines(session, item_ids)


async def throughput(
    session: AsyncSession,
    project_id: uuid.UUID,
    start: date,
    end: date,
    interval: ReportInterval,
    *,
    actor: User | None = None,
    q: str | None = None,
) -> list[ThroughputBucket]:
    """Per bucket, the number of items that ENTERED a done-category state in it."""
    timelines = await _project_timelines(session, project_id, actor, q)
    counts = {bucket: 0 for bucket in bucket_starts(start, end, interval)}
    for item in timelines.values():
        for entry in item.done_entries:
            day = entry.at.date()
            if start <= day <= end:
                bucket = bucket_start(day, interval)
                if bucket in counts:
                    counts[bucket] += 1
    return [
        ThroughputBucket(bucket=bucket.isoformat(), count=count)
        for bucket, count in sorted(counts.items())
    ]


async def cumulative_flow(
    session: AsyncSession,
    project_id: uuid.UUID,
    start: date,
    end: date,
    interval: ReportInterval,
    *,
    actor: User | None = None,
    q: str | None = None,
) -> list[CumulativeFlowBucket]:
    """Per bucket, how many items sat in each StateCategory at the bucket's end."""
    timelines = await _project_timelines(session, project_id, actor, q)
    step = timedelta(weeks=1) if interval is ReportInterval.WEEK else timedelta(days=1)
    result: list[CumulativeFlowBucket] = []
    for bucket in bucket_starts(start, end, interval):
        moment = _end_of(bucket + step - timedelta(days=1))
        counts = {category.value: 0 for category in StateCategory}
        for item in timelines.values():
            category = item.category_at(moment)
            if category is not None:
                counts[category.value] += 1
        result.append(CumulativeFlowBucket(bucket=bucket.isoformat(), counts=counts))
    return result


async def time_in_state(
    session: AsyncSession,
    project_id: uuid.UUID,
    kind: ItemKind | None = None,
    *,
    actor: User | None = None,
    q: str | None = None,
) -> list[TimeInStateRow]:
    """Avg + median hours items spent in each category (completed segments only)."""
    timelines = await _project_timelines(session, project_id, actor, q)
    durations: dict[StateCategory, list[float]] = {category: [] for category in StateCategory}
    for item in timelines.values():
        if kind is not None and item.kind != kind.value:
            continue
        for segment in item.segments:
            if segment.exited_at is None:
                continue  # still in this state — not a completed stay
            hours = (segment.exited_at - segment.entered_at).total_seconds() / 3600
            durations[segment.category].append(hours)
    rows: list[TimeInStateRow] = []
    for category in StateCategory:
        samples = durations[category]
        if not samples:
            continue
        rows.append(
            TimeInStateRow(
                category=category,
                avg_hours=round(statistics.mean(samples), 2),
                median_hours=round(statistics.median(samples), 2),
                sample=len(samples),
            )
        )
    return rows


async def _points_measure(
    session: AsyncSession, measure: ReportMeasure, item_ids: list[uuid.UUID]
) -> dict[uuid.UUID, float] | None:
    """The CURRENT points per item when measuring in points (spec 70), else None
    (count mode — exact pre-70 behavior). Unset points count as 0."""
    if measure is not ReportMeasure.POINTS:
        return None
    return await items_service.estimate_points_by_ids(session, item_ids)


def _measure_of(ids: list[uuid.UUID], points: dict[uuid.UUID, float] | None) -> int | float:
    """len() in count mode; the one-decimal point sum in points mode."""
    if points is None:
        return len(ids)
    return round(sum(points.get(item_id, 0.0) for item_id in ids), 1)


async def velocity(
    session: AsyncSession,
    last: int,
    measure: ReportMeasure = ReportMeasure.COUNT,
    *,
    actor: User | None = None,
    q: str | None = None,
) -> VelocityReport:
    """For the last N completed cycles, items that entered done while assigned to
    them — counted, or summed as story points (spec 70, `measure=points`).

    Cycles span projects, so the figure is cross-project and carries the scope it
    was computed over (RADD-789)."""
    if actor is not None and not await authz.holds(session, actor, authz.Permission.CYCLE_READ):
        # Like the cycle directory, return an empty collection when the
        # catalog atom is absent. Project-only readers still receive their
        # report scope without disclosure of cycle names or timeline data.
        return VelocityReport(rows=[], scope=await report_scope(session, actor))
    recent = await cycles_service.recent_completed_cycles(session, actor=actor, limit=last, today=date.today())
    if not recent:
        # Keep SLQ/field-access validation even for an empty cycle directory.
        await matching_ids(session, actor, q, candidate_ids=[])
    # A draft can be explicitly completed without planned dates. Use its actual
    # completion day for ordering, then creation as the final legacy fallback.
    def finished_on(cycle):
        return cycle.completed_at.date() if cycle.completed_at else cycle.end_date or cycle.created_at.date()

    rows: list[VelocityRow] = []
    for cycle in sorted(recent, key=lambda cycle: (cycle.start_date or finished_on(cycle), cycle.id)):
        item_ids, timelines = await _cycle_timelines(session, cycle.id, actor, q)
        points = await _points_measure(session, measure, item_ids)
        done_ids = [
            item_id
            for item_id, item in timelines.items()
            if any(entry.cycle_id == cycle.id for entry in item.done_entries)
        ]
        rows.append(
            VelocityRow(
                cycle=CycleBrief(id=cycle.id, name=cycle.name),
                completed=_measure_of(done_ids, points),
            )
        )
    return VelocityReport(rows=rows, scope=await report_scope(session, actor))


async def burnup(
    session: AsyncSession,
    cycle_id: uuid.UUID,
    measure: ReportMeasure = ReportMeasure.COUNT,
    *,
    actor: User | None = None,
    q: str | None = None,
) -> BurnupSeries:
    """Daily scope (items in the cycle) vs completed, over the cycle's window —
    item counts, or story-point sums over the same sets (spec 70)."""
    cycle = await cycles_service.get_cycle(session, cycle_id)
    if actor is not None:
        await authz.require(session, actor, authz.Permission.CYCLE_READ)
        if not await cycles_service.cycle_visible_to(session, cycle, actor):
            raise NotFoundError(CycleEntity.CYCLE, cycle_id)
    if cycle.start_date is None or cycle.end_date is None:
        # A DRAFT (staging) cycle has no window to plot — schedule it first.
        raise ConflictError(
            CycleEntity.CYCLE, reason="burnup needs a scheduled cycle (set start and end dates)"
        )
    item_ids, timelines = await _cycle_timelines(session, cycle.id, actor, q)
    points = await _points_measure(session, measure, item_ids)
    series: list[BurnupPoint] = []
    day = cycle.start_date
    while day <= cycle.end_date:
        moment = _end_of(day)
        scope_ids = [
            item_id
            for item_id, item in timelines.items()
            if item.cycle_at(moment) == cycle.id
        ]
        completed_ids = [
            item_id
            for item_id, item in timelines.items()
            if any(
                entry.cycle_id == cycle.id and entry.at <= moment for entry in item.done_entries
            )
        ]
        series.append(
            BurnupPoint(
                date=day.isoformat(),
                scope=_measure_of(scope_ids, points),
                completed=_measure_of(completed_ids, points),
            )
        )
        day += timedelta(days=1)
    return BurnupSeries(
        cycle=CycleWindow(
            id=cycle.id, name=cycle.name, start_date=cycle.start_date, end_date=cycle.end_date
        ),
        series=series,
        scope=await report_scope(session, actor),
    )
