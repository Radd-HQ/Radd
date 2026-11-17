"""Write an item's state/cycle history as it happens (RADD-1537).

`record` is called wherever an item event carrying the item's snapshot is
emitted — the same moments the reports used to rediscover by folding the ledger —
and writes a row only when the state or the cycle actually differs from the
item's previous row. Calling it when nothing moved is therefore safe, and is the
point: the emitters do not each have to know what counts as a transition.

Readers (`reporting`, `slas`) query `ItemTransition` directly; it is a spine
table like `WorkItem`.
"""

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from radd.clock import utcnow
from radd.modules.workflow.models import State
from radd.modules.workflow.types import StateCategory

from .models import ItemTransition, WorkItem


async def record(session: AsyncSession, item: WorkItem, *, at: datetime | None = None) -> None:
    """Note `item`'s current state and cycle if either changed since its last row.

    `at` backdates an import (naive UTC), exactly as the event it accompanies is
    backdated; the row order stays insertion order.
    """
    state = await session.get(State, item.state_id)
    if state is None:
        return  # a state deleted under the item: nothing to place the stay in
    last = await session.scalar(
        select(ItemTransition)
        .where(ItemTransition.item_id == item.id)
        .order_by(ItemTransition.id.desc())
        .limit(1)
    )
    if last is not None and last.project_id != item.project_id:
        # A cross-project move: the item's whole history reports where it is now.
        await session.execute(
            update(ItemTransition)
            .where(ItemTransition.item_id == item.id)
            .values(project_id=item.project_id)
        )
    state_changed = last is None or last.state_id != state.id
    if not state_changed and last.cycle_id == item.cycle_id:
        return
    moment = (at or utcnow()).replace(tzinfo=None)
    done = StateCategory.DONE.value
    session.add(
        ItemTransition(
            item_id=item.id,
            project_id=item.project_id,
            at=moment,
            state_id=state.id,
            category=state.category,
            cycle_id=item.cycle_id,
            state_changed=state_changed,
            entered_done=(
                state_changed
                and state.category == done
                and (last is None or last.category != done)
            ),
            stay_at=moment if state_changed else last.stay_at,
            from_state_id=last.state_id if last is not None and state_changed else None,
            from_category=last.category if last is not None and state_changed else None,
            from_at=last.stay_at if last is not None and state_changed else None,
            from_cycle_id=last.cycle_id if last is not None else None,
        )
    )
    await session.flush()
