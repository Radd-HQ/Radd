"""Reconstruct each work item's state history from the events outbox.

`item.created`/`item.updated` payloads carry the FULL item (docs/modules.md), so a
work item's state transitions are recoverable by walking its events in order and
diffing `state.id`/`state.category` between consecutive payloads. The event row's
`created_at` is the authoritative moment of each transition.

Everything the reports need is derived here in one pass per item:

- `segments`      — the ordered (entered_at, exited_at, state_id, category) the item
                    passed through (an open final segment has `exited_at is None`);
- `done_entries`  — each moment the item ENTERED a done-category state, tagged with the
                    cycle it belonged to at that moment (velocity/throughput source);
- `cycle_history` — the (at, cycle_id) assignment trail (burnup scope-over-time source).

No new tables: recomputing from events is acceptable at prototype scale (materialize
into a projection later — see docs/modules.md).
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.events.models import Event
from radd.modules.items.enums import ItemEntity, ItemEvent
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
    project_id: uuid.UUID | None
    kind: str | None
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


def _build(item_id: uuid.UUID, events: list[Event]) -> ItemTimeline:
    """Fold an item's ordered event payloads into a timeline (pure over the rows)."""
    timeline = ItemTimeline(item_id=item_id, project_id=None, kind=None)
    prev_category: StateCategory | None = None
    for event in events:
        payload = event.payload
        state = payload.get("state") or {}
        state_id = uuid.UUID(state["id"])
        category = StateCategory(state["category"])
        cycle = payload.get("cycle")
        cycle_id = uuid.UUID(cycle["id"]) if cycle else None
        at = event.created_at

        if timeline.project_id is None and payload.get("project_id"):
            timeline.project_id = uuid.UUID(payload["project_id"])
        if timeline.kind is None:
            timeline.kind = payload.get("kind")
        timeline.cycle_history.append((at, cycle_id))

        state_changed = not timeline.segments or timeline.segments[-1].state_id != state_id
        if state_changed:
            if timeline.segments:
                last = timeline.segments[-1]
                timeline.segments[-1] = StateSegment(
                    last.entered_at, at, last.state_id, last.category
                )
            timeline.segments.append(StateSegment(at, None, state_id, category))
            if category is StateCategory.DONE and prev_category is not StateCategory.DONE:
                timeline.done_entries.append(DoneEntry(at=at, cycle_id=cycle_id))
        prev_category = category
    return timeline


async def _item_events(
    session: AsyncSession, item_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, list[Event]]:
    ids = {str(item_id) for item_id in item_ids}
    if not ids:
        return {}
    rows = (
        await session.execute(
            select(Event)
            .where(
                Event.entity_type == str(ItemEntity.ITEM),
                Event.entity_id.in_(ids),
                Event.event_type.in_((str(ItemEvent.CREATED), str(ItemEvent.UPDATED))),
            )
            .order_by(Event.id)
        )
    ).scalars()
    grouped: dict[uuid.UUID, list[Event]] = {}
    for event in rows:
        grouped.setdefault(uuid.UUID(event.entity_id), []).append(event)
    return grouped


async def build_item_timelines(
    session: AsyncSession, item_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, ItemTimeline]:
    """The workhorse: per item, the full reconstructed timeline from its event history."""
    grouped = await _item_events(session, item_ids)
    return {item_id: _build(item_id, events) for item_id, events in grouped.items()}


async def item_state_timeline(
    session: AsyncSession, item_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, list[StateSegment]]:
    """Per item, the ordered (entered_at, state_id, category) segments from its event
    history — the primitive the throughput / cumulative-flow / time-in-state reports
    compute over (spec 16)."""
    timelines = await build_item_timelines(session, item_ids)
    return {item_id: timeline.segments for item_id, timeline in timelines.items()}


# --- scope resolution (which items a report ranges over) — also read from the outbox ---


async def item_ids_for_project(session: AsyncSession, project_id: uuid.UUID) -> list[uuid.UUID]:
    """Ids of items created in the project (from `item.created` payloads — project is immutable)."""
    rows = (
        await session.execute(
            select(Event.entity_id).where(
                Event.entity_type == str(ItemEntity.ITEM),
                Event.event_type == str(ItemEvent.CREATED),
                Event.payload["project_id"].astext == str(project_id),
            )
        )
    ).scalars()
    return [uuid.UUID(entity_id) for entity_id in rows]


async def item_ids_for_cycle(session: AsyncSession, cycle_id: uuid.UUID) -> list[uuid.UUID]:
    """Ids of items ever assigned to the cycle (any event whose payload cycle matches)."""
    rows = (
        await session.execute(
            select(Event.entity_id)
            .where(
                Event.entity_type == str(ItemEntity.ITEM),
                Event.payload["cycle"]["id"].astext == str(cycle_id),
            )
            .distinct()
        )
    ).scalars()
    return [uuid.UUID(entity_id) for entity_id in rows]
