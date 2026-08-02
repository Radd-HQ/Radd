"""Orphan GC for comments (RADD-717 follow-up).

**This is the correctness mechanism, not an optimization.** The polymorphic
parent column cannot carry a foreign key, so `ON DELETE CASCADE` is gone. Both
hard-delete paths call `service.delete_for_parent` directly, which handles the
common case immediately — but that is a promise every FUTURE delete path has to
remember to keep, and a comment whose parent is gone is invisible in the UI and
unreachable by any API. Nobody would ever notice.

So the guarantee is made structural here instead: whatever else happens, when a
parent's `*.deleted` event goes by, its comments go with it.

**The event map comes from the binding registry, not from a constant.** A plugin
that registers a `CommentParent` declares its own `deleted_event`, so it gets
cleanup with no edit to this module — which is the whole reason the polymorphic
parent was worth its cost. (`attachments/gc.py` hardcodes the equivalent map,
and that is precisely the seam a plugin cannot reach; this is the same pattern
with the last hardcoded piece removed.)

Head-seeded, like every other consumer: the historical backlog must not replay
as a wave of deletes on first start.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.modules.events import runner
from radd.modules.events.models import Event
from radd.worker import PeriodicLoop

from .models import Comment

logger = logging.getLogger(__name__)

CONSUMER_NAME = "comments.gc"
BATCH_SIZE = 50


def _parent_deletes() -> dict[str, str]:
    """{event type -> entity type}, live from the registry.

    Imported inside the function: `parents` reaches into `items`, which imports
    back this way round, so a module-scope import would close the cycle.
    """
    from .parents import bindings

    return {binding.deleted_event: binding.entity_type for binding in bindings()}


async def run_once() -> int:
    return await runner.run_head_seeded(
        CONSUMER_NAME, batch_size=BATCH_SIZE, plan=_plan, deliver=_deliver
    )


async def _plan(session: AsyncSession, event: Event) -> None:
    """Delete in the PLANNING transaction, which the runner commits with the
    cursor — so a crash between the two cannot lose the work or repeat it."""
    entity_type = _parent_deletes().get(event.event_type)
    if entity_type is None:
        return None
    try:
        parent_id = uuid.UUID(str(event.entity_id))
    except ValueError:
        return None
    result = await session.execute(
        delete(Comment).where(
            Comment.entity_type == entity_type, Comment.entity_id == parent_id
        )
    )
    # Usually zero: the delete path swept them a moment earlier. A non-zero
    # count means something bypassed that path, which is exactly what this
    # consumer exists to catch — so it is worth a line in the log.
    if result.rowcount:
        logger.info(
            "comments.gc: %s %s took %d orphaned comment(s)",
            entity_type, parent_id, result.rowcount,
        )
    return None


async def _deliver(_plans: list[None]) -> None:
    """Nothing happens after the commit — the rows are the whole job."""


_loop = PeriodicLoop(
    run_once,
    interval=lambda: settings.search_poll_interval,  # the indexers' cadence fits
    name=CONSUMER_NAME,
    enabled=lambda: settings.run_workers,
)


async def start() -> None:
    await _loop.start()


async def stop() -> None:
    await _loop.stop()
