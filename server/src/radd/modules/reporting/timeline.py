"""One item's state history as the SLA timers want it: per item the state
`segments` (an open final one has `exited_at is None`) and the `done_entries`
(tagged with the cycle at that moment).

Read from `item_transitions` (RADD-1537). The project-wide reports aggregate
that table in SQL (`service.py`); this per-item view is for callers that need
the stays themselves, over a bounded set of items.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from itertools import batched

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.items.models import ItemTransition
from radd.modules.workflow.types import StateCategory


@dataclass(frozen=True)
class StateSegment:
    """One contiguous stay in a single state. `exited_at is None` = still there."""

    entered_at: datetime
    exited_at: datetime | None
    state_id: uuid.UUID
    category: StateCategory


@dataclass(frozen=True)
class DoneEntry:
    """The item entered a done-category state at `at`, assigned to `cycle_id` then."""

    at: datetime
    cycle_id: uuid.UUID | None


@dataclass
class ItemTimeline:
    item_id: uuid.UUID
    segments: list[StateSegment] = field(default_factory=list)
    done_entries: list[DoneEntry] = field(default_factory=list)


async def build_item_timelines(
    session: AsyncSession, item_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, ItemTimeline]:
    """Per item, its timeline. Items with no recorded history are absent."""
    out: dict[uuid.UUID, ItemTimeline] = {}
    for batch in batched(dict.fromkeys(item_ids), 1000):
        rows = await session.execute(
            select(
                ItemTransition.item_id,
                ItemTransition.at,
                ItemTransition.state_id,
                ItemTransition.category,
                ItemTransition.cycle_id,
                ItemTransition.state_changed,
                ItemTransition.entered_done,
            )
            .where(ItemTransition.item_id.in_(batch))
            .order_by(ItemTransition.item_id, ItemTransition.id)
        )
        for item_id, at, state_id, category, cycle_id, state_changed, entered_done in rows:
            timeline = out.get(item_id)
            if timeline is None:
                timeline = out[item_id] = ItemTimeline(item_id=item_id)
            if not state_changed:
                continue
            if timeline.segments:
                last = timeline.segments[-1]
                timeline.segments[-1] = StateSegment(
                    last.entered_at, at, last.state_id, last.category
                )
            timeline.segments.append(StateSegment(at, None, state_id, StateCategory(category)))
            if entered_done:
                timeline.done_entries.append(DoneEntry(at=at, cycle_id=cycle_id))
    return out
