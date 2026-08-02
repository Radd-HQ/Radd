"""Read seam for the SLA report (spec 63): the engine's `sla_item_states`
bookkeeping joined to the items they belong to, optionally scoped to one
project. Consumed by the reporting module's `/reports/sla`.

Deliberately imports ONLY models: `slas/service.py` imports
`reporting/timeline.py`, so this file must not touch either package's service
layer or the two modules would import-cycle.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.items.models import WorkItem

from .models import SlaItemState, SlaPolicy


@dataclass(frozen=True)
class SlaStateRow:
    """One (item, policy) bookkeeping row with the item's creation stamp."""

    item_id: uuid.UUID
    item_created_at: datetime
    response_met_at: datetime | None
    response_breached_at: datetime | None
    resolution_met_at: datetime | None
    resolution_breached_at: datetime | None


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
