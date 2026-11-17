"""Read-only analytics (spec 16), aggregated in SQL over `item_transitions`
(RADD-1537): each report is one grouped query over the rows its own window
covers, where it used to load a project's whole event history and fold it in
Python. `bucket_start(s)`, `matching_ids` and `report_scope` are public so a
plugin's own report (the SLA report in `slas`, RADD-1386) buckets the same way."""

import uuid
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, NotFoundError
from radd.modules.auth import authz
from radd.modules.auth.models import User
from radd.modules.cycles import service as cycles_service
from radd.modules.cycles.types import CycleEntity
from radd.modules.items import bulk as items_bulk
from radd.modules.items import service as items_service
from radd.modules.items.enums import ItemKind
from radd.modules.items.models import ItemTransition, WorkItem
from radd.modules.workflow.types import StateCategory

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


async def _visible(
    session: AsyncSession, actor: User | None, q: str | None, project_id: uuid.UUID | None = None
):
    """The SELECT of item ids a report may range over, or None with no actor
    (unfiltered). The reports hand it to the database as a subquery: the
    intersection used to be a Python set of every visible id in the project."""
    if actor is None:
        return None
    return await items_bulk.visible_matching_select(
        session, actor=actor, q=(q or "").strip() or None, project_id=project_id
    )


def _scoped(query, visible):
    return query if visible is None else query.where(ItemTransition.item_id.in_(visible))


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time.min)


def throughput_statement(project_id: uuid.UUID, start: date, end: date):
    """Done-entries per calendar day inside `[start, end]` — the whole read a
    throughput report makes, public so a test can ask the planner what it touches."""
    day = func.date(ItemTransition.at)
    return (
        select(day, func.count())
        .where(
            ItemTransition.project_id == project_id,
            ItemTransition.entered_done,
            ItemTransition.at >= _midnight(start),
            ItemTransition.at < _midnight(end + timedelta(days=1)),
        )
        .group_by(day)
    )


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
    """Per bucket, the number of items that ENTERED a done-category state in it.

    One grouped read of the report's own window: `(project_id, at)` is indexed,
    so a 30-day report over an eight-year project touches 30 days of rows."""
    visible = await _visible(session, actor, q, project_id)
    rows = await session.execute(_scoped(throughput_statement(project_id, start, end), visible))
    counts = {bucket: 0 for bucket in bucket_starts(start, end, interval)}
    for entered_on, count in rows:
        bucket = bucket_start(entered_on, interval)
        if bucket in counts:
            counts[bucket] += count
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
    """Per bucket, how many items sat in each StateCategory at the bucket's end.

    Every state change adds one to the category entered and takes one from the
    category left, so the distribution at a moment is the running sum of those
    deltas. The database sums them: everything up to the first bucket collapses
    into one opening balance, and the window itself comes back as one row per
    day and category pair — never one row per item."""
    step = timedelta(weeks=1) if interval is ReportInterval.WEEK else timedelta(days=1)
    #: Each bucket is read at the midnight that ENDS its last day.
    closing_days = [
        (bucket, bucket + step - timedelta(days=1)) for bucket in bucket_starts(start, end, interval)
    ]
    if not closing_days:
        return []
    visible = await _visible(session, actor, q, project_id)
    opening_day = closing_days[0][1]
    # A change counts toward the day whose closing midnight is the first at or
    # after it, hence the microsecond: one made exactly at midnight belongs to
    # the day that midnight closes.
    counted_on = func.greatest(
        func.date(ItemTransition.at - timedelta(microseconds=1)), opening_day
    )
    rows = await session.execute(
        _scoped(
            select(counted_on, ItemTransition.category, ItemTransition.from_category, func.count())
            .where(
                ItemTransition.project_id == project_id,
                ItemTransition.state_changed,
                ItemTransition.at <= _end_of(closing_days[-1][1]),
            )
            .group_by(counted_on, ItemTransition.category, ItemTransition.from_category),
            visible,
        )
    )
    deltas: dict[date, dict[str, int]] = {}
    for day, entered, left, count in rows:
        change = deltas.setdefault(day, {})
        change[entered] = change.get(entered, 0) + count
        if left is not None:
            change[left] = change.get(left, 0) - count
    pending = sorted(deltas)
    counts = {category.value: 0 for category in StateCategory}
    result: list[CumulativeFlowBucket] = []
    for bucket, closing_day in closing_days:
        while pending and pending[0] <= closing_day:
            for category, delta in deltas[pending.pop(0)].items():
                counts[category] = counts.get(category, 0) + delta
        result.append(CumulativeFlowBucket(bucket=bucket.isoformat(), counts=dict(counts)))
    return result


async def time_in_state(
    session: AsyncSession,
    project_id: uuid.UUID,
    kind: ItemKind | None = None,
    *,
    actor: User | None = None,
    q: str | None = None,
) -> list[TimeInStateRow]:
    """Avg + median hours items spent in each category (completed stays only).

    A state change carries when the state it left was entered (`from_at`), so a
    completed stay is one row and the statistics are one aggregate. `kind` is
    the item's kind NOW (it was the kind at creation while this folded events;
    they differ only for a converted item)."""
    visible = await _visible(session, actor, q, project_id)
    hours = func.extract("epoch", ItemTransition.at - ItemTransition.from_at) / 3600.0
    query = (
        select(
            ItemTransition.from_category,
            func.avg(hours),
            func.percentile_cont(0.5).within_group(hours),
            func.count(),
        )
        .where(
            ItemTransition.project_id == project_id,
            ItemTransition.state_changed,
            ItemTransition.from_at.is_not(None),
        )
        .group_by(ItemTransition.from_category)
    )
    if kind is not None:
        query = query.join(WorkItem, WorkItem.id == ItemTransition.item_id).where(
            WorkItem.kind == kind.value
        )
    measured = {
        category: (average, median, sample)
        for category, average, median, sample in await session.execute(_scoped(query, visible))
    }
    return [
        TimeInStateRow(
            category=category,
            avg_hours=round(float(measured[category.value][0]), 2),
            median_hours=round(float(measured[category.value][1]), 2),
            sample=measured[category.value][2],
        )
        for category in StateCategory
        if category.value in measured
    ]


async def _points_measure(
    session: AsyncSession, measure: ReportMeasure, item_ids: list[uuid.UUID]
) -> dict[uuid.UUID, float] | None:
    """The CURRENT points per item when measuring in points (spec 70), else None
    (count mode — exact pre-70 behavior). Unset points count as 0."""
    if measure is not ReportMeasure.POINTS:
        return None
    return await items_service.estimate_points_by_ids(session, item_ids)


def _measure_of(ids: Iterable[uuid.UUID], points: dict[uuid.UUID, float] | None) -> int | float:
    """A count in count mode; the one-decimal point sum in points mode."""
    ids = list(ids)
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
    # Compiled even for an empty cycle directory: SLQ and field-access
    # validation answer the same 422 whether or not there is anything to count.
    visible = await _visible(session, actor, q)
    done: dict[uuid.UUID, set[uuid.UUID]] = {cycle.id: set() for cycle in recent}
    if recent:
        rows = await session.execute(
            _scoped(
                select(ItemTransition.cycle_id, ItemTransition.item_id)
                .where(ItemTransition.entered_done, ItemTransition.cycle_id.in_(list(done)))
                .distinct(),
                visible,
            )
        )
        for cycle_id, item_id in rows:
            done[cycle_id].add(item_id)
    points = await _points_measure(
        session, measure, [item_id for ids in done.values() for item_id in ids]
    )

    # A draft can be explicitly completed without planned dates. Use its actual
    # completion day for ordering, then creation as the final legacy fallback.
    def finished_on(cycle):
        return cycle.completed_at.date() if cycle.completed_at else cycle.end_date or cycle.created_at.date()

    rows_out = [
        VelocityRow(
            cycle=CycleBrief(id=cycle.id, name=cycle.name),
            completed=_measure_of(done[cycle.id], points),
        )
        for cycle in sorted(recent, key=lambda cycle: (cycle.start_date or finished_on(cycle), cycle.id))
    ]
    return VelocityReport(rows=rows_out, scope=await report_scope(session, actor))


async def burnup(
    session: AsyncSession,
    cycle_id: uuid.UUID,
    measure: ReportMeasure = ReportMeasure.COUNT,
    *,
    actor: User | None = None,
    q: str | None = None,
) -> BurnupSeries:
    """Daily scope (items in the cycle) vs completed, over the cycle's window —
    item counts, or story-point sums over the same sets (spec 70).

    Reads only the rows that happened IN the cycle or LEFT it (both indexed), so
    the work is proportional to the cycle, not to the projects it draws from."""
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
    visible = await _visible(session, actor, q)
    rows = await session.execute(
        _scoped(
            select(
                ItemTransition.item_id,
                ItemTransition.at,
                ItemTransition.cycle_id,
                ItemTransition.entered_done,
            )
            .where(or_(ItemTransition.cycle_id == cycle.id, ItemTransition.from_cycle_id == cycle.id))
            .order_by(ItemTransition.id),
            visible,
        )
    )
    #: Per item: each moment its membership of THIS cycle was restated, in order,
    #: and the first moment it entered done while a member.
    membership: dict[uuid.UUID, list[tuple[datetime, bool]]] = {}
    completed_at: dict[uuid.UUID, datetime] = {}
    for item_id, at, row_cycle, entered_done in rows:
        member = row_cycle == cycle.id
        membership.setdefault(item_id, []).append((at, member))
        if member and entered_done:
            completed_at[item_id] = min(at, completed_at.get(item_id, at))
    points = await _points_measure(session, measure, list(membership))

    def member_at(history: list[tuple[datetime, bool]], moment: datetime) -> bool:
        result = False
        for at, member in history:
            if at > moment:
                break
            result = member
        return result

    series: list[BurnupPoint] = []
    day = cycle.start_date
    while day <= cycle.end_date:
        moment = _end_of(day)
        series.append(
            BurnupPoint(
                date=day.isoformat(),
                scope=_measure_of(
                    (item_id for item_id, history in membership.items() if member_at(history, moment)),
                    points,
                ),
                completed=_measure_of(
                    (item_id for item_id, at in completed_at.items() if at <= moment), points
                ),
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
