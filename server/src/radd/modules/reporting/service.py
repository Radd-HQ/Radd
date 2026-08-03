"""Read-only analytics computed on the fly from the event log + cycles (spec 16).

Each report is a small, mostly-pure fold over the reconstructed item timelines
(`timeline.py`). Nothing is persisted.
"""

import statistics
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError
from radd.modules.auth import authz
from radd.modules.auth.models import User
# Submodule with model-only imports (the slas/report.py idiom) — csat loads
# AFTER reporting in RADD_MODULES, so this must never touch its service layer.
from radd.modules.csat import report as csat_responses
from radd.modules.cycles import service as cycles_service
from radd.modules.cycles.types import CycleEntity, CycleStatus
from radd.modules.items import bulk as items_bulk
from radd.modules.items import service as items_service
from radd.modules.items.enums import ItemKind
# Submodule with model-only imports — safe against the slas↔reporting cycle
# (slas/service.py imports reporting/timeline.py); see slas/report.py.
from radd.modules.slas import report as sla_states
from radd.modules.workflow.types import StateCategory

from . import timeline
from .schemas import (
    BurnupPoint,
    BurnupSeries,
    CumulativeFlowBucket,
    CycleBrief,
    CycleWindow,
    ReportScope,
    SlaReport,
    SlaReportBucket,
    ThroughputBucket,
    TimeInStateRow,
    VelocityReport,
    VelocityRow,
)
from .types import ReportInterval, ReportMeasure

DEFAULT_WINDOW_DAYS = 30
SLA_REPORT_DEFAULT_WEEKS = 12
SLA_REPORT_MAX_WEEKS = 26


# --- bucketing ---


def _bucket_start(day: date, interval: ReportInterval) -> date:
    """The date that labels `day`'s bucket (the Monday of its week, or the day itself)."""
    if interval is ReportInterval.WEEK:
        return day - timedelta(days=day.weekday())
    return day


def _bucket_starts(start: date, end: date, interval: ReportInterval) -> list[date]:
    step = timedelta(weeks=1) if interval is ReportInterval.WEEK else timedelta(days=1)
    cursor = _bucket_start(start, interval)
    buckets: list[date] = []
    while cursor <= end:
        buckets.append(cursor)
        cursor += step
    return buckets


def _end_of(day: date) -> datetime:
    """The instant just past midnight after `day` — used as an end-of-day snapshot point."""
    return datetime.combine(day + timedelta(days=1), time.min)


# --- reports ---


# --- the dashboard-wide SLQ filter seam ------------------------------------
# Every report folds over an item-id UNIVERSE before touching history; the
# filter intersects that universe with the SLQ's CURRENT matches (visibility
# included — items/bulk.visible_matching_ids). Deliberate semantics: SLQ
# evaluates an item's state TODAY, so `assignee = me` means "items assigned
# to me now — report that subset's history", the pragmatic reading every
# tracker picks. An uncompilable q raises SlqError → the usual 422.


async def _matching_ids(
    session: AsyncSession,
    actor: User | None,
    q: str | None,
    project_id: uuid.UUID | None = None,
) -> set[uuid.UUID] | None:
    """The item ids a report may range over. None = unfiltered (no actor).

    This used to return None whenever `q` was absent, which meant the ONLY thing
    narrowing a cross-project report was the dashboard query — and without one,
    `sla_report(project_id=None)` folded every project's bookkeeping rows into
    the average (RADD-789). The global `item.read` gate was all that stood in
    front of it, and RADD-788 relaxed that gate, so the two land together.

    Now visibility is always applied and the query is intersected on top: one
    mechanism, and the RBAC half cannot be skipped by omitting `q`.
    `visible_matching_ids` already constrains a cross-project read to the
    readable projects up front (RADD-672), so this is the same rule `GET /items`
    follows rather than a second copy of it.
    """
    if actor is None:
        return None
    return await items_bulk.visible_matching_ids(
        session, actor=actor, q=(q or "").strip() or None, project_id=project_id
    )


async def _scope_of(session: AsyncSession, actor: User | None) -> ReportScope:
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
    matches = await _matching_ids(session, actor, q, project_id)
    item_ids = _keep(await timeline.item_ids_for_project(session, project_id), matches)
    timelines = await timeline.build_item_timelines(session, item_ids)
    counts = {bucket: 0 for bucket in _bucket_starts(start, end, interval)}
    for item in timelines.values():
        for entry in item.done_entries:
            day = entry.at.date()
            if start <= day <= end:
                bucket = _bucket_start(day, interval)
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
    matches = await _matching_ids(session, actor, q, project_id)
    item_ids = _keep(await timeline.item_ids_for_project(session, project_id), matches)
    timelines = await timeline.build_item_timelines(session, item_ids)
    step = timedelta(weeks=1) if interval is ReportInterval.WEEK else timedelta(days=1)
    result: list[CumulativeFlowBucket] = []
    for bucket in _bucket_starts(start, end, interval):
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
    matches = await _matching_ids(session, actor, q, project_id)
    item_ids = _keep(await timeline.item_ids_for_project(session, project_id), matches)
    timelines = await timeline.build_item_timelines(session, item_ids)
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
    matches = await _matching_ids(session, actor, q)
    today = date.today()
    completed = await cycles_service.list_cycles(
        session, status=CycleStatus.COMPLETED, today=today
    )
    recent = sorted(completed, key=lambda cycle: cycle.end_date, reverse=True)[:last]
    rows: list[VelocityRow] = []
    for cycle in sorted(recent, key=lambda cycle: cycle.start_date):
        item_ids = _keep(await timeline.item_ids_for_cycle(session, cycle.id), matches)
        timelines = await timeline.build_item_timelines(session, item_ids)
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
    return VelocityReport(rows=rows, scope=await _scope_of(session, actor))


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
    if cycle.start_date is None or cycle.end_date is None:
        # A DRAFT (staging) cycle has no window to plot — schedule it first.
        raise ConflictError(
            CycleEntity.CYCLE, reason="burnup needs a scheduled cycle (set start and end dates)"
        )
    matches = await _matching_ids(session, actor, q)
    item_ids = _keep(await timeline.item_ids_for_cycle(session, cycle.id), matches)
    timelines = await timeline.build_item_timelines(session, item_ids)
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
        scope=await _scope_of(session, actor),
    )


# --- service desk (spec 63) ---


@dataclass
class _SlaWeekFold:
    """Mutable per-week accumulator for the service-desk report (specs 63+65)."""

    items: int = 0
    response_met: int = 0
    response_breached: int = 0
    resolution_met: int = 0
    resolution_breached: int = 0
    breached_items: int = 0
    response_seconds: list[float] = field(default_factory=list)
    resolution_seconds: list[float] = field(default_factory=list)
    csat_ratings: list[int] = field(default_factory=list)  # spec 65

    def to_bucket(self, week: date) -> SlaReportBucket:
        return SlaReportBucket(
            week=week.isoformat(),
            items=self.items,
            response_met=self.response_met,
            response_breached=self.response_breached,
            resolution_met=self.resolution_met,
            resolution_breached=self.resolution_breached,
            breach_rate=round(self.breached_items / self.items, 4) if self.items else 0.0,
            avg_response_seconds=(
                round(statistics.mean(self.response_seconds), 1) if self.response_seconds else None
            ),
            avg_resolution_seconds=(
                round(statistics.mean(self.resolution_seconds), 1)
                if self.resolution_seconds
                else None
            ),
            csat_avg=(
                round(statistics.mean(self.csat_ratings), 2) if self.csat_ratings else None
            ),
            csat_count=len(self.csat_ratings),
        )


async def sla_report(
    session: AsyncSession,
    project_id: uuid.UUID | None,
    weeks: int,
    *,
    actor: User | None = None,
    q: str | None = None,
) -> SlaReport:
    """Weekly SLA outcomes over the engine's bookkeeping rows, bucketed by the
    week each ITEM was created. "Met" = met without a breach stamp ("met late"
    counts as breached); averages are wall-clock from item creation to the met
    stamp (business-time-adjusted averages are a later refinement)."""
    first_week = _bucket_start(date.today(), ReportInterval.WEEK) - timedelta(weeks=weeks - 1)
    rows = await sla_states.state_rows(
        session, project_id, since=datetime.combine(first_week, time.min)
    )
    matches = await _matching_ids(session, actor, q, project_id)
    if matches is not None:
        rows = [row for row in rows if row.item_id in matches]
    # An item may carry several bookkeeping rows (pre-spec-63 evaluate-all era):
    # fold per item first — earliest met stamps, any breach stamp counts.
    per_item: dict[uuid.UUID, sla_states.SlaStateRow] = {}
    for row in rows:
        seen = per_item.get(row.item_id)
        if seen is None:
            per_item[row.item_id] = row
            continue
        per_item[row.item_id] = sla_states.SlaStateRow(
            item_id=row.item_id,
            item_created_at=row.item_created_at,
            response_met_at=min(
                (at for at in (seen.response_met_at, row.response_met_at) if at is not None),
                default=None,
            ),
            response_breached_at=seen.response_breached_at or row.response_breached_at,
            resolution_met_at=min(
                (at for at in (seen.resolution_met_at, row.resolution_met_at) if at is not None),
                default=None,
            ),
            resolution_breached_at=seen.resolution_breached_at or row.resolution_breached_at,
        )

    folds = {week: _SlaWeekFold() for week in _bucket_starts(first_week, date.today(), ReportInterval.WEEK)}
    for row in per_item.values():
        week = _bucket_start(row.item_created_at.date(), ReportInterval.WEEK)
        fold = folds.get(week)
        if fold is None:
            continue
        fold.items += 1
        if row.response_breached_at is not None:
            fold.response_breached += 1
        elif row.response_met_at is not None:
            fold.response_met += 1
        if row.resolution_breached_at is not None:
            fold.resolution_breached += 1
        elif row.resolution_met_at is not None:
            fold.resolution_met += 1
        if row.response_breached_at is not None or row.resolution_breached_at is not None:
            fold.breached_items += 1
        if row.response_met_at is not None:
            fold.response_seconds.append(
                (row.response_met_at - row.item_created_at).total_seconds()
            )
        if row.resolution_met_at is not None:
            fold.resolution_seconds.append(
                (row.resolution_met_at - row.item_created_at).total_seconds()
            )

    # CSAT (spec 65) — NOTE the deliberate asymmetry: the SLA counters above
    # bucket by the week the ITEM was created; ratings bucket by the week the
    # RESPONSE arrived (responded_at). A rating landing weeks after the item was
    # raised counts in the week it was given, so the trend shows sentiment as it
    # actually arrives.
    csat_rows = await csat_responses.responded_rows(
        session, project_id, since=datetime.combine(first_week, time.min)
    )
    for csat_row in csat_rows:
        # Same visibility intersection as the SLA counters above (RADD-789) — a
        # rating is as project-scoped as the item it was given about.
        if matches is not None and csat_row.item_id not in matches:
            continue
        fold = folds.get(_bucket_start(csat_row.responded_at.date(), ReportInterval.WEEK))
        if fold is not None:
            fold.csat_ratings.append(csat_row.rating)
    return SlaReport(
        buckets=[fold.to_bucket(week) for week, fold in sorted(folds.items())],
        scope=await _scope_of(session, actor),
    )
