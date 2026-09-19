"""Run history (RADD-1266): recording, reading and sweeping automation runs.

A separate module from `service.py` for the reason `round_robin.py` is: the
graph's CRUD is one concern and what its runs left behind is another, and the
service file was already past nine hundred lines.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.clock import utcnow
from radd.config import settings
from radd.exceptions import NotFoundError

from .executor import RunReport
from .models import AutomationRun
from .schemas import RuleTestResult
from .types import RunSource, RunStatus

logger = logging.getLogger(__name__)

#: Keys kept on the row for the list view — enough to recognise a run.
ITEM_KEYS_KEPT = 10


def status_of(report: RunReport) -> RunStatus:
    """How the run ended, from what the walk planned. Ranked: a refusal is what
    someone opens the row to learn about, so it wins over the actions that did
    apply beside it."""
    if any(plan.refused for plan in report.plans):
        return RunStatus.REFUSED
    if any(plan.resolves for plan in report.plans):
        return RunStatus.APPLIED
    return RunStatus.NOTHING_TO_DO


async def record(
    session: AsyncSession,
    *,
    automation_id: uuid.UUID,
    trigger_node_id: str,
    source: RunSource,
    event_id: int | None,
    event_type: str,
    started_at: datetime,
    actor_id: uuid.UUID | None,
    status: RunStatus,
    result: RuleTestResult | None,
    item_keys: list[str] = (),
    error: str = "",
) -> AutomationRun:
    """Write the row, in the caller's transaction. The engine's consumer commits
    per event, so a run and its record land together or not at all."""
    plans = result.would_apply if result is not None else []
    row = AutomationRun(
        automation_id=automation_id,
        trigger_node_id=trigger_node_id,
        source=source.value,
        event_id=event_id,
        event_type=event_type,
        started_at=started_at,
        finished_at=utcnow(),
        status=status.value,
        actor_id=actor_id,
        item_keys=list(item_keys)[:ITEM_KEYS_KEPT],
        actions_applied=sum(1 for plan in plans if plan.resolves),
        actions_skipped=sum(1 for plan in plans if not plan.resolves),
        error=error[:2000],
        report=result.model_dump(mode="json") if result is not None else {},
    )
    session.add(row)
    await session.flush()
    return row


async def list_runs(
    session: AsyncSession,
    automation_id: uuid.UUID,
    *,
    limit: int = 50,
    before: datetime | None = None,
) -> list[AutomationRun]:
    """Newest first, keyset-paged on `started_at`."""
    query = (
        select(AutomationRun)
        .where(AutomationRun.automation_id == automation_id)
        .order_by(AutomationRun.started_at.desc(), AutomationRun.id.desc())
        .limit(max(1, min(limit, 200)))
    )
    if before is not None:
        query = query.where(AutomationRun.started_at < before)
    return list((await session.execute(query)).scalars())


async def get_run(session: AsyncSession, automation_id: uuid.UUID, run_id: uuid.UUID) -> AutomationRun:
    row = await session.get(AutomationRun, run_id)
    if row is None or row.automation_id != automation_id:
        raise NotFoundError("automation_run", run_id)
    return row


async def last_runs(
    session: AsyncSession, automation_ids: list[uuid.UUID]
) -> dict[uuid.UUID, AutomationRun]:
    """The newest run per automation, in one query — the list page's chip."""
    if not automation_ids:
        return {}
    latest = (
        select(
            AutomationRun.automation_id,
            func.max(AutomationRun.started_at).label("started_at"),
        )
        .where(AutomationRun.automation_id.in_(automation_ids))
        .group_by(AutomationRun.automation_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(AutomationRun).join(
                latest,
                (AutomationRun.automation_id == latest.c.automation_id)
                & (AutomationRun.started_at == latest.c.started_at),
            )
        )
    ).scalars()
    return {row.automation_id: row for row in rows}


async def sweep(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Delete runs older than `automation_run_retention_days`. Called from the
    scheduler's tick; cheap because of the started_at index."""
    days = settings.automation_run_retention_days
    if days <= 0:
        return 0
    cutoff = (now or utcnow()) - timedelta(days=days)
    result = await session.execute(delete(AutomationRun).where(AutomationRun.started_at < cutoff))
    removed = result.rowcount or 0
    if removed:
        logger.info("automations: swept %d run(s) older than %d days", removed, days)
    return removed
