"""Answered surveys for the SLA report — read by slas through a weak edge."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.items.models import WorkItem

from .models import CsatSurvey


@dataclass(frozen=True)
class CsatResponseRow:
    """One answered survey; `item_id` lets the caller intersect with the items
    the reader may see (RADD-789)."""

    rating: int
    responded_at: datetime
    item_id: uuid.UUID


async def responded_rows(
    session: AsyncSession,
    project_id: uuid.UUID | None,
    since: datetime,
) -> list[CsatResponseRow]:
    """Answered surveys whose RESPONSE arrived since `since`, optionally scoped
    to one project."""
    query = (
        select(CsatSurvey.rating, CsatSurvey.responded_at, CsatSurvey.item_id)
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
