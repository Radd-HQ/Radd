"""Head-seeded two-phase consumer scaffold (`run_head_seeded`).

For consumers that DELIVER outside the database (a mail, a survey, a storage
delete) and must never do it twice:

- no cursor yet → it is seeded AT THE STREAM HEAD (first start only;
  `ConsumerResume.HEAD` covers re-enable, RADD-1372);
- the cursor is claimed for the tick (`consumer.claim`, RADD-1538), so a second
  worker process does not plan the same batch;
- `plan` each event (planning may write rows). A plan that raises is recorded in
  `consumer_failures` as dead — at-most-once means it is not retried, not that it
  vanishes;
- advance the cursor and COMMIT before any delivery, then `deliver` post-commit:
  a dropped message beats a duplicate.

`silent` (bulk-import) events are skipped. Consumers that only write to the
database declare a `consumer.Consumer` instead.
"""

import logging
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import SessionLocal

from . import consumer as consumers, service
from .models import Event

logger = logging.getLogger(__name__)

#: `{consumer name: (plan, deliver)}` for every scaffold consumer that has run in
#: this process — how an operator's replay finds them.
head_seeded: dict[str, tuple[Callable, Callable]] = {}


async def run_head_seeded[P](
    consumer_name: str,
    *,
    batch_size: int,
    plan: Callable[[AsyncSession, Event], Awaitable[P | None]],
    deliver: Callable[[list[P]], Awaitable[None]],
) -> int:
    """One consumer iteration (see module docstring). Returns the number of
    events consumed (0 on first-start seeding / an empty stream)."""
    head_seeded[consumer_name] = (plan, deliver)
    async with SessionLocal() as session:
        offset = await consumers.claim(session, consumer_name, consumers.FirstStart.HEAD)
        if offset is None:
            return 0
        batch = await service.read_after(session, offset, batch_size)
        if not batch:
            await session.commit()  # a cursor seeded just now must outlive the tick
            return 0
        deliveries: list[tuple[Event, list[P]]] = []
        previous_cause = None
        for event in batch:
            # A `silent` bulk-import event must not trigger delivery; the cursor still advances.
            if event.silent:
                continue
            try:
                async with session.begin_nested():
                    with service.derived_from(event):
                        planned = await plan(session, event)
            except Exception as error:  # noqa: BLE001 — a plan may raise anything
                logger.exception("%s: planning failed for event %s", consumer_name, event.id)
                await consumers.record_failure(
                    session, consumer_name, event.id, error, consumers.Delivery.AT_MOST_ONCE
                )
                continue
            if planned is not None:
                cause = (event.automated, event.automation_rule_id, event.automation_depth, event.silent)
                if cause != previous_cause:
                    deliveries.append((event, []))
                    previous_cause = cause
                deliveries[-1][1].append(planned)
        await service.set_offset(session, consumer_name, batch[-1])
        await session.commit()  # planning writes + the cursor land BEFORE delivery
    for event, plans in deliveries:  # post-commit, post-cursor: at-most-once delivery
        with service.derived_from(event):
            await deliver(plans)
    return len(batch)


async def replay(session: AsyncSession, consumer_name: str, event: Event) -> bool:
    """An operator asked for a failed event again: plan it, commit, deliver."""
    plan, deliver = head_seeded[consumer_name]
    try:
        async with session.begin_nested():
            with service.derived_from(event):
                planned = await plan(session, event)
    except Exception as error:  # noqa: BLE001
        logger.exception("%s: replay failed for event %s", consumer_name, event.id)
        await consumers.record_failure(
            session, consumer_name, event.id, error, consumers.Delivery.AT_MOST_ONCE
        )
        return False
    await session.commit()
    if planned is not None:
        with service.derived_from(event):
            await deliver([planned])
    return True
