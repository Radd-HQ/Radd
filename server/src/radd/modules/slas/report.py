"""The service-desk SLA report (specs 63/65): weekly SLA outcomes over the
engine's `sla_item_states` bookkeeping, plus CSAT ratings when csat is loaded.

It lived in `reporting` for historical reasons, which made a core module import
two optional plugins (RADD-1386). It folds with reporting's public machinery —
the ISO-week buckets, the reader's item universe and the scope note — so the
dependency runs one way: slas → reporting.

CSAT is a WEAK edge between two optional plugins (`weak_depends=("csat",)`):
checked against the live plugin registry on every request, so disabling csat at
runtime drops the ratings without a restart, and imported only after that check.
"""

import statistics
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.kernel import registries
from radd.modules.auth.models import User
from radd.modules.items.models import WorkItem
from radd.modules.reporting import service as reporting
from radd.modules.reporting.types import ReportInterval

from .models import SlaItemState, SlaPolicy
from .schemas import SlaReport, SlaReportBucket
from .types import CSAT_PLUGIN_ID


@dataclass(frozen=True)
class SlaStateRow:
    """One (item, policy) bookkeeping row with the item's creation stamp."""

    item_id: uuid.UUID
    item_created_at: datetime
    response_met_at: datetime | None
    response_breached_at: datetime | None
    resolution_met_at: datetime | None
    resolution_breached_at: datetime | None


@dataclass(frozen=True)
class Rating:
    """One answered survey, as the report needs it."""

    item_id: uuid.UUID
    responded_at: datetime
    rating: int


async def state_rows(
    session: AsyncSession,
    project_id: uuid.UUID | None,
    since: datetime,
) -> list[SlaStateRow]:
    """Bookkeeping rows for items CREATED since `since` (optionally one project)."""
    query = (
        select(
            SlaItemState.item_id,
            WorkItem.created_at,
            SlaItemState.response_met_at,
            SlaItemState.response_breached_at,
            SlaItemState.resolution_met_at,
            SlaItemState.resolution_breached_at,
        )
        .join(WorkItem, WorkItem.id == SlaItemState.item_id)
        .join(SlaPolicy, SlaPolicy.id == SlaItemState.policy_id)
        .where(WorkItem.created_at >= since)
    )
    if project_id is not None:
        query = query.where(WorkItem.project_id == project_id)
    return [SlaStateRow(*row) for row in (await session.execute(query)).all()]


async def ratings(
    session: AsyncSession, project_id: uuid.UUID | None, since: datetime
) -> list[Rating]:
    """Answered surveys since `since` — none while the csat plugin is not loaded."""
    if CSAT_PLUGIN_ID not in registries.plugins:
        return []
    from radd.modules.csat import report as csat_report

    rows = await csat_report.responded_rows(session, project_id, since=since)
    return [Rating(row.item_id, row.responded_at, row.rating) for row in rows]


def _fold_per_item(rows: list[SlaStateRow]) -> list[SlaStateRow]:
    """An item may carry several bookkeeping rows (pre-spec-63 evaluate-all era):
    one per item — earliest met stamps, and any breach stamp counts."""
    per_item: dict[uuid.UUID, SlaStateRow] = {}
    for row in rows:
        seen = per_item.get(row.item_id)
        if seen is None:
            per_item[row.item_id] = row
            continue
        per_item[row.item_id] = SlaStateRow(
            item_id=row.item_id,
            item_created_at=row.item_created_at,
            response_met_at=_earliest(seen.response_met_at, row.response_met_at),
            response_breached_at=seen.response_breached_at or row.response_breached_at,
            resolution_met_at=_earliest(seen.resolution_met_at, row.resolution_met_at),
            resolution_breached_at=seen.resolution_breached_at or row.resolution_breached_at,
        )
    return list(per_item.values())


def _earliest(*stamps: datetime | None) -> datetime | None:
    return min((at for at in stamps if at is not None), default=None)


def _mean(samples: list[float] | list[int], digits: int) -> float | None:
    return round(statistics.mean(samples), digits) if samples else None


@dataclass
class _WeekFold:
    """Mutable per-week accumulator (specs 63+65)."""

    items: int = 0
    response_met: int = 0
    response_breached: int = 0
    resolution_met: int = 0
    resolution_breached: int = 0
    breached_items: int = 0
    response_seconds: list[float] = field(default_factory=list)
    resolution_seconds: list[float] = field(default_factory=list)
    csat_ratings: list[int] = field(default_factory=list)

    def add(self, row: SlaStateRow) -> None:
        """A met stamp without a breach stamp is met; "met late" counts as breached."""
        self.items += 1
        if row.response_breached_at is not None:
            self.response_breached += 1
        elif row.response_met_at is not None:
            self.response_met += 1
        if row.resolution_breached_at is not None:
            self.resolution_breached += 1
        elif row.resolution_met_at is not None:
            self.resolution_met += 1
        if row.response_breached_at is not None or row.resolution_breached_at is not None:
            self.breached_items += 1
        if row.response_met_at is not None:
            self.response_seconds.append((row.response_met_at - row.item_created_at).total_seconds())
        if row.resolution_met_at is not None:
            self.resolution_seconds.append(
                (row.resolution_met_at - row.item_created_at).total_seconds()
            )

    def to_bucket(self, week: date) -> SlaReportBucket:
        return SlaReportBucket(
            week=week.isoformat(),
            items=self.items,
            response_met=self.response_met,
            response_breached=self.response_breached,
            resolution_met=self.resolution_met,
            resolution_breached=self.resolution_breached,
            breach_rate=round(self.breached_items / self.items, 4) if self.items else 0.0,
            avg_response_seconds=_mean(self.response_seconds, 1),
            avg_resolution_seconds=_mean(self.resolution_seconds, 1),
            csat_avg=_mean(self.csat_ratings, 2),
            csat_count=len(self.csat_ratings),
        )


def _week_of(moment: datetime) -> date:
    return reporting.bucket_start(moment.date(), ReportInterval.WEEK)


async def sla_report(
    session: AsyncSession,
    project_id: uuid.UUID | None,
    weeks: int,
    *,
    actor: User | None = None,
    q: str | None = None,
) -> SlaReport:
    """Weekly SLA outcomes over the engine's bookkeeping rows, bucketed by the
    week each ITEM was created. Averages are wall-clock from item creation to the
    met stamp (business-time-adjusted averages are a later refinement)."""
    today = date.today()
    first_week = reporting.bucket_start(today, ReportInterval.WEEK) - timedelta(weeks=weeks - 1)
    since = datetime.combine(first_week, time.min)
    rows = await state_rows(session, project_id, since=since)
    matches = await reporting.matching_ids(
        session, actor, q, project_id, candidate_ids=list({row.item_id for row in rows})
    )
    if matches is not None:
        rows = [row for row in rows if row.item_id in matches]

    folds = {
        week: _WeekFold()
        for week in reporting.bucket_starts(first_week, today, ReportInterval.WEEK)
    }
    for row in _fold_per_item(rows):
        fold = folds.get(_week_of(row.item_created_at))
        if fold is not None:
            fold.add(row)

    # CSAT (spec 65) — NOTE the deliberate asymmetry: the SLA counters above
    # bucket by the week the ITEM was created; ratings bucket by the week the
    # RESPONSE arrived. A rating landing weeks after the item was raised counts
    # in the week it was given, so the trend shows sentiment as it arrives.
    for rating in await ratings(session, project_id, since=since):
        # Same visibility intersection as the SLA counters (RADD-789) — a rating
        # is as project-scoped as the item it was given about.
        if matches is not None and rating.item_id not in matches:
            continue
        fold = folds.get(_week_of(rating.responded_at))
        if fold is not None:
            fold.csat_ratings.append(rating.rating)
    return SlaReport(
        buckets=[fold.to_bucket(week) for week, fold in sorted(folds.items())],
        scope=await reporting.report_scope(session, actor),
    )
