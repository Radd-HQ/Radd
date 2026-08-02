"""Read seam for the service-desk report (spec 65): answered surveys joined to
their items, optionally scoped to one project. Consumed by the reporting
module's `/reports/sla` (csat_avg/csat_count on the weekly buckets).

Deliberately imports ONLY models (the slas/report.py precedent): reporting loads
BEFORE csat in RADD_MODULES, so reporting cannot declare csat in depends_on —
a models-only read keeps the edge safe."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.items.models import WorkItem

from .models import CsatSurvey


@dataclass(frozen=True)
class CsatResponseRow:
    """One answered survey: what rating landed, and when."""

    rating: int
    responded_at: datetime


async def responded_rows(
    session: AsyncSession,
    project_id: uuid.UUID | None,
    since: datetime,
) -> list[CsatResponseRow]:
    """Answered surveys whose RESPONSE arrived since `since`, optionally scoped
    to one project."""
    query = (
        select(CsatSurvey.rating, CsatSurvey.responded_at)
        .join(WorkItem, WorkItem.id == CsatSurvey.item_id)
        .where(
            CsatSurvey.rating.is_not(None),
            CsatSurvey.responded_at.is_not(None),
            CsatSurvey.responded_at >= since,
        )
    )
    if project_id is not None:
        query = query.where(WorkItem.project_id == project_id)
    return [CsatResponseRow(*row) for row in (await session.execute(query)).all()]
