"""Head-seeded outbox-consumer scaffold (consolidation).

The delivery-flavored consumers — csat's survey sender, the googlechat
notifier, mailintake's outbound replies — share one run_once shape, extracted
here:

- no offset row yet → seed the cursor AT THE STREAM HEAD, commit, log, return 0
  (a chat channel / requester inbox must never be replayed the historical
  backlog). That covers a consumer's FIRST start only; one that must also skip
  what happened while its plugin was disabled declares
  `ConsumerResume.HEAD` on its plugin, and the plugin manager moves its cursor
  to the head when the plugin is re-enabled (RADD-1372);
- read one batch after the cursor;
- build per-event delivery "plans" via the `plan` callback (log-don't-crash per
  event; planning MAY write rows through the session — csat creates survey rows
  and emits csat.requested while planning);
- advance the cursor and COMMIT everything BEFORE any delivery, then hand the
  plans to `deliver` post-commit — at-most-once: a dropped message beats a
  duplicate.

Consumers with real semantic differences stay hand-rolled: search's indexer
(replays the backlog from 0 as its index build, savepoint per event), notify
(watch-only bootstrap OVER the backlog), the automations engine (one
transaction per event), webhooks (fan-out rows ARE the delivery).

Every consumer here delivers OUTSIDE the instance, so all of them skip `silent`
events (`events.quiet()` — bulk imports). Search's indexer deliberately does not.
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
            # Every consumer on this scaffold DELIVERS somewhere external (a survey
            # email, a chat message, a requester reply), which is exactly what a
            # `silent` bulk-import event must not trigger. The cursor still advances.
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
