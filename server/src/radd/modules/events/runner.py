"""Head-seeded outbox-consumer scaffold (`run_head_seeded`).

- no offset row yet → seed the cursor AT THE STREAM HEAD and return (first start only;
  `ConsumerResume.HEAD` covers re-enable, RADD-1372);
- read one batch; `plan` each event (log-don't-crash; planning may write rows);
- advance the cursor and COMMIT before any delivery, then `deliver` post-commit —
  at-most-once: a dropped message beats a duplicate.

`silent` (bulk-import) events are skipped. Consumers with different semantics (search
indexer, notify, automations, webhooks) stay hand-rolled.
"""

import logging
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import SessionLocal

from . import service
from .models import Event

logger = logging.getLogger(__name__)


async def run_head_seeded[P](
    consumer_name: str,
    *,
    batch_size: int,
    plan: Callable[[AsyncSession, Event], Awaitable[P | None]],
    deliver: Callable[[list[P]], Awaitable[None]],
) -> int:
    """One consumer iteration (see module docstring). Returns the number of
    events consumed (0 on first-start seeding / an empty stream)."""
    async with SessionLocal() as session:
        if not await service.offset_exists(session, consumer_name):
            head = await service.latest_event_id(session)
            await service.set_offset(session, consumer_name, head)
            await session.commit()
            logger.info(
                "%s: first start — cursor seeded at stream head %s", consumer_name, head
            )
            return 0
        offset = await service.get_offset(session, consumer_name)
        batch = await service.read_after(session, offset, batch_size)
        if not batch:
            return 0
        deliveries: list[tuple[Event, list[P]]] = []
        previous_cause = None
        for event in batch:
            # A `silent` bulk-import event must not trigger delivery; the cursor still advances.
            if event.silent:
                continue
            try:
                with service.derived_from(event):
                    planned = await plan(session, event)
            except Exception:
                logger.exception("%s: planning failed for event %s", consumer_name, event.id)
                continue
            if planned is not None:
                cause = (event.automated, event.automation_rule_id, event.automation_depth, event.silent)
                if cause != previous_cause:
                    deliveries.append((event, []))
                    previous_cause = cause
                deliveries[-1][1].append(planned)
        await service.set_offset(session, consumer_name, batch[-1].id)
        await session.commit()  # planning writes + the cursor land BEFORE delivery
    for event, plans in deliveries:  # post-commit, post-cursor: at-most-once delivery
        with service.derived_from(event):
            await deliver(plans)
    return len(batch)
