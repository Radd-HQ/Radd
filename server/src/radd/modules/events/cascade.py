"""The cascade consumer (RADD-745): one loop drains the stream for every registered
`CascadeSpec` (see its docstring for the contract). One consumer rather than one per owner:
a cascade is a DELETE that usually matches nothing, not worth its own cursor and poll."""

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


async def run_once() -> int:
    return await runner.run_head_seeded(
        CONSUMER_NAME, batch_size=settings.event_cascade_batch, plan=_plan, deliver=_deliver
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
