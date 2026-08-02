"""Item↔cycle stint history (spec 56).

The items service calls `record_cycle_change` on every cycle assignment change
(create + update — the complete-cycle carryover move routes through update):
the open stint for the old cycle is closed, a new one opens for the new cycle.
`work_items.cycle_id` stays the current-cycle truth; these rows are the
queryable past (SLQ `past_cycle`, the item view's "Previous cycles" chips).
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Cycle, ItemCycleRecord


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def record_cycle_change(
    session: AsyncSession,
    *,
    item_id: uuid.UUID,
    old_cycle_id: uuid.UUID | None,
    new_cycle_id: uuid.UUID | None,
    at: datetime | None = None,
) -> None:
    """Close the old cycle's open stint and open one for the new cycle.

    No-op when unchanged. Re-entering a cycle the item left earlier opens a
    SECOND stint — the history keeps every visit, not just membership.
    `at` lets the importer stamp original times (mirrors created_at overrides).
    """
    if old_cycle_id == new_cycle_id:
        return
    stamp = at or _now()
    if old_cycle_id is not None:
        await session.execute(
            update(ItemCycleRecord)
            .where(
                ItemCycleRecord.item_id == item_id,
                ItemCycleRecord.cycle_id == old_cycle_id,
                ItemCycleRecord.removed_at.is_(None),
            )
            .values(removed_at=stamp)
        )
    if new_cycle_id is not None:
        session.add(ItemCycleRecord(item_id=item_id, cycle_id=new_cycle_id, added_at=stamp))
    await session.flush()


async def past_cycles_by_item_ids(
    session: AsyncSession, item_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[Cycle]]:
    """item_id -> cycles of CLOSED stints, oldest first, deduped (an item that
    visited a cycle twice lists it once). The open stint is `item.cycle`."""
    if not item_ids:
        return {}
    rows = await session.execute(
        select(ItemCycleRecord.item_id, Cycle)
        .join(Cycle, Cycle.id == ItemCycleRecord.cycle_id)
        .where(
            ItemCycleRecord.item_id.in_(item_ids),
            ItemCycleRecord.removed_at.is_not(None),
        )
        .order_by(ItemCycleRecord.added_at.asc())
    )
    result: dict[uuid.UUID, list[Cycle]] = {}
    for item_id, cycle in rows:
        bucket = result.setdefault(item_id, [])
        if all(existing.id != cycle.id for existing in bucket):
            bucket.append(cycle)
    return result
