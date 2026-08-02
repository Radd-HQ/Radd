"""The cascade consumer (RADD-745): one loop for every "died with its parent".

Three registries had independently grown the same hole. `attachments` and
`comments` key rows to a POLYMORPHIC parent (`entity_type` + `entity_id`), which
cannot carry a foreign key, so `ON DELETE CASCADE` is unavailable. `access_grants`
keys to `resource_type` + `resource_id` for the same reason. Each answered it
differently: two head-seeded consumers, plus four call sites in access that have
to remember.

This is the one answer. Modules register a `CascadeSpec` on their manifest and
this consumer drains the stream once for all of them.

**Why one and not three.** There were already eighteen `PeriodicLoop`s polling
this instance. A cascade is not worth its own cursor, its own poll interval and
its own query of the events table — the work is a `DELETE … WHERE parent = ?`
that usually matches nothing, because the delete path swept it a moment earlier.
Registering costs a dict entry; a consumer costs a task per process forever.

**Why the kernel and not a shared base class.** A plugin must be able to register
cleanup for its own rows without editing a module it does not own. That was the
entire justification for the polymorphic parent, and hardcoded maps inside each
GC were quietly taking it back.

`sweep` runs in the planning transaction (committed with the cursor, so a crash
cannot lose or repeat it); whatever it returns goes to `after_commit`, for the
effects that must not run inside a transaction — attachments removes bytes from a
storage host there, where an unreachable host must leave orphaned bytes rather
than a stuck consumer.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.kernel.registry import registries
from radd.worker import PeriodicLoop

from . import runner
from .models import Event

logger = logging.getLogger(__name__)

CONSUMER_NAME = "events.cascade"
BATCH_SIZE = 50


async def run_once() -> int:
    return await runner.run_head_seeded(
        CONSUMER_NAME, batch_size=BATCH_SIZE, plan=_plan, deliver=_deliver
    )


async def _plan(session: AsyncSession, event: Event) -> list[tuple[Any, Any]] | None:
    """Run every cascade registered for this event, in the planning transaction."""
    specs = registries.cascades_for(event.event_type)
    if not specs:
        return None
    try:
        parent_id = uuid.UUID(str(event.entity_id))
    except (ValueError, TypeError):
        return None

    carried: list[tuple[Any, Any]] = []
    for spec in specs:
        try:
            result = await spec.sweep(session, parent_id)
        except Exception:  # noqa: BLE001
            # One module's cleanup must not stop another's, nor wedge the cursor
            # on a row that will never succeed. Loud, and the stream moves on.
            logger.exception("cascade %s failed for %s %s", spec.name, event.event_type, parent_id)
            continue
        if result and spec.after_commit is not None:
            carried.append((spec, result))
    return carried or None


async def _deliver(plans: list[list[tuple[Any, Any]]]) -> None:
    """Post-commit effects — bytes, remote calls. Best effort, never fatal."""
    for carried in plans:
        for spec, result in carried:
            try:
                await spec.after_commit(result)
            except Exception:  # noqa: BLE001
                logger.warning("cascade %s post-commit failed", spec.name, exc_info=True)


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
