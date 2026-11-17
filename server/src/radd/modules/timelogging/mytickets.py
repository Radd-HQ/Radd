"""The issues a person is likely to log time on next (RADD-1572).

One ranked list from three reads: what is assigned to them and still open, what
they booked time on lately, and what they acted on lately — any item-scoped
event they caused, read from the event log. The third is the one the entry
calendar's trays could not show: the issue commented on or moved an hour ago is
usually the one the hour belongs to.

The "acted" read names no event types. It asks the kernel registry which types
are item-scoped, so a module that adds one is counted without this file
knowing, and its reason is that type's registered label.

Viewing an issue is not a signal on purpose: nothing records it, and a write on
every page open is not worth a tray.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.clock import utcnow
from radd.config import settings
from radd.kernel import registries
from radd.modules.auth import authz
from radd.modules.auth.models import User
from radd.modules.events import service as events_service
from radd.modules.events.types import EventSource
from radd.modules.items import service as items_service
from radd.modules.items.models import WorkItem
from radd.modules.projects import service as projects_service
from radd.modules.workflow.models import State
from radd.modules.workflow.types import StateCategory

from . import enablement
from .models import Worklog
from .schemas import MyTicket
from .types import TicketReason, WorklogEvent

_CLOSED = (StateCategory.DONE.value, StateCategory.CANCELED.value)


@dataclass
class _Candidate:
    """Why one issue is on the list, and when each reason last held."""

    at: dict[TicketReason, datetime] = field(default_factory=dict)
    activity: str = ""  # the label of their newest event on it

    def note(self, reason: TicketReason, when: datetime) -> None:
        if reason not in self.at or when > self.at[reason]:
            self.at[reason] = when


def _acted_event_types() -> list[str]:
    """Every registered item-scoped event type but this module's own: booking
    time is the LOGGED reason, with the day it was booked for."""
    own = {event.value for event in WorklogEvent}
    return sorted(
        event_type
        for event_type, spec in registries.event_types.items()
        if spec.item_scoped and event_type not in own
    )


def _event_item_id(payload: dict) -> uuid.UUID | None:
    ref = payload.get("item")
    try:
        return uuid.UUID(str(ref["id"])) if isinstance(ref, dict) else None
    except (KeyError, ValueError):
        return None


async def my_tickets(
    session: AsyncSession, actor: User, *, now: datetime | None = None
) -> list[MyTicket]:
    now = now or utcnow()
    since = now - timedelta(days=settings.timelog_my_tickets_days)
    found: dict[uuid.UUID, _Candidate] = {}

    assigned = await session.execute(
        select(WorkItem.id, WorkItem.updated_at)
        .join(State, State.id == WorkItem.state_id)
        .where(
            WorkItem.assignee_id == actor.id,
            WorkItem.archived_at.is_(None),
            State.category.not_in(_CLOSED),
        )
        .order_by(WorkItem.updated_at.desc())
        .limit(settings.timelog_my_tickets_limit)
    )
    for item_id, updated_at in assigned:
        found.setdefault(item_id, _Candidate()).note(TicketReason.ASSIGNED, updated_at)

    logged = await session.execute(
        select(Worklog.item_id, func.max(Worklog.worked_on))
        .where(
            Worklog.author_id == actor.id,
            Worklog.item_id.is_not(None),
            Worklog.worked_on >= since.date(),
        )
        .group_by(Worklog.item_id)
    )
    for item_id, worked_on in logged:
        # A day has no hour: noon ranks a day's booking among that day's events.
        found.setdefault(item_id, _Candidate()).note(
            TicketReason.LOGGED, min(datetime.combine(worked_on, time(12)), now)
        )

    event_types = _acted_event_types()
    events = (
        await events_service.query_events(
            session,
            actor_id=actor.id,
            event_types=event_types,
            source=EventSource.PEOPLE,
            start=since,
            limit=settings.timelog_my_tickets_events,
        )
        if event_types
        else []
    )
    for event in events:  # newest first
        item_id = _event_item_id(event.payload)
        if item_id is None:
            continue
        candidate = found.setdefault(item_id, _Candidate())
        if TicketReason.ACTED not in candidate.at:
            candidate.activity = registries.event_types[event.event_type].label
        candidate.note(TicketReason.ACTED, event.created_at)

    if not found:
        return []
    readable = await items_service.readable_item_ids(session, actor, found)
    ranked = sorted(
        ((item_id, found[item_id]) for item_id in readable),
        key=lambda pair: max(pair[1].at.values()),
        reverse=True,
    )[: settings.timelog_my_tickets_limit]
    ids = [item_id for item_id, _ in ranked]
    if not ids:
        return []

    rows = {
        row.id: row
        for row in await session.execute(
            select(WorkItem.id, WorkItem.project_id, WorkItem.number, WorkItem.title).where(
                WorkItem.id.in_(ids), WorkItem.archived_at.is_(None)
            )
        )
    }
    seconds = dict(
        (
            await session.execute(
                select(Worklog.item_id, func.sum(Worklog.time_spent_seconds))
                .where(Worklog.author_id == actor.id, Worklog.item_id.in_(ids))
                .group_by(Worklog.item_id)
            )
        ).all()
    )
    readable_projects = set(await authz.readable_projects(session, actor))
    keys = {
        project.id: project.key
        for project in await projects_service.list_projects(session)
        if project.id in readable_projects
    }
    takes_time = await enablement.enabled_project_ids(session)

    tickets: list[MyTicket] = []
    for item_id, candidate in ranked:
        row = rows.get(item_id)
        if row is None or row.project_id not in keys:
            continue
        newest = max(candidate.at, key=lambda reason: candidate.at[reason])
        tickets.append(
            MyTicket(
                id=item_id,
                key=f"{keys[row.project_id]}-{row.number}",
                title=row.title,
                project_id=row.project_id,
                reasons=sorted(candidate.at, key=lambda reason: candidate.at[reason], reverse=True),
                activity=candidate.activity if newest is TicketReason.ACTED else "",
                last_at=candidate.at[newest],
                my_seconds=int(seconds.get(item_id, 0)),
                loggable=row.project_id in takes_time,
            )
        )
    return tickets
