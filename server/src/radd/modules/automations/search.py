"""The SLQ source node (RADD-919): find issues and pass them downstream.

The only built-in node that PRODUCES items (every other kind narrows what the
trigger handed it), so it works under any trigger — a schedule included — and
runs on an empty packet. REPLACE is the default mode; see `SearchMode`.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.modules.items.models import WorkItem

logger = logging.getLogger(__name__)


async def find_items(
    session: AsyncSession,
    query: str,
    *,
    project_key: str = "",
    limit: int | None = None,
    label: str = "search",
) -> list[uuid.UUID]:
    """Active items matching `query`, in rank order, capped.

    The cap is `automation_schedule_max_items` — the same one the scheduler has
    always used, because "how many items may one automation run touch" is one
    question and two numbers would eventually disagree. Truncation is LOGGED: a
    run that hit the ceiling and one that genuinely matched 200 items are
    otherwise indistinguishable.

    An empty query returns nothing rather than everything. A half-filled form is
    the likeliest source of one, and "" meaning "every issue in the instance" is
    the most expensive possible reading of a mistake.
    """
    text = (query or "").strip()
    if not text:
        return []

    # Deferred: `planning` imports this module's siblings, and importing it at
    # module scope makes the automations package import order load-bearing.
    from .planning import _project_by_key, compile_slq

    project = None
    if project_key.strip():
        project = await _project_by_key(session, project_key)
        if project is None:
            logger.warning("automations: %s: no project %r — no items", label, project_key)
            return []

    compiled = await compile_slq(session, text, project)

    cap = min(limit or settings.automation_schedule_max_items, settings.automation_schedule_max_items)
    stmt = (
        select(WorkItem.id)
        .where(WorkItem.archived_at.is_(None))
        .order_by(WorkItem.rank)
        .limit(cap + 1)
    )
    if project is not None:
        stmt = stmt.where(WorkItem.project_id == project.id)
    if compiled.where is not None:
        stmt = stmt.where(compiled.where)

    ids = list((await session.execute(stmt)).scalars())
    if len(ids) > cap:
        logger.info("automations: %s matched over %d items — truncated to the cap", label, cap)
        ids = ids[:cap]
    return ids
