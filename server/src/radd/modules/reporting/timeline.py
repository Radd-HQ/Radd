"""One item's state history as the SLA timers want it: per item the state
`segments` (an open final one has `exited_at is None`), the `done_entries`
(tagged with the cycle at that moment) and the `cycle_history`.

Read from `item_transitions` (RADD-1537) — a handful of narrow rows per item,
written when the change happened. It used to be rebuilt per request from the
event ledger, every `item.created`/`item.updated` with its full item snapshot.
The project-wide REPORTS no longer build timelines at all: they aggregate the
same table in SQL (`service.py`). This per-item view remains for callers that
need the stays themselves, over a bounded set of items.
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
    cycle_history: list[tuple[datetime, uuid.UUID | None]] = field(default_factory=list)

    def category_at(self, moment: datetime) -> StateCategory | None:
        """Category of the segment active at `moment`; None if the item didn't exist yet."""
        result: StateCategory | None = None
        for segment in self.segments:
            if segment.entered_at <= moment:
                result = segment.category
            else:
                break
        return result

    def cycle_at(self, moment: datetime) -> uuid.UUID | None:
        """Cycle the item was assigned to at `moment` (None if unset or not yet created)."""
        result: uuid.UUID | None = None
        for at, cycle_id in self.cycle_history:
            if at <= moment:
                result = cycle_id
            else:
                break
        return result


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
            timeline.cycle_history.append((at, cycle_id))
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
