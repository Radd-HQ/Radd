"""Who could hear about an item event, split by RELATION (spec 118) — the four
sets the matrix's columns are about. A page's audience is its subject
provider's (`subjects.py`)."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from radd.kernel import sockets
from radd.kernel.sockets import Socket
from radd.modules.auth import service as auth
from radd.modules.events.service import Event
from radd.modules.items.models import WorkItem
from radd.modules.teams import service as teams

from . import service
from .planner import Audience
from .rules import Subject


async def recipient_ids(session: AsyncSession, item_id: uuid.UUID) -> frozenset[uuid.UUID]:
    """The PARTICIPATING set: watchers ∪ what every live `NOTIFICATION_AUDIENCE`
    source adds (participants: CURRENT members of the item's participant teams).
    Through the kernel socket, so a disabled plugin stops widening it; every
    recipient still passes `consumer._allowed`."""
    recipients = set(await service.watcher_ids(session, item_id))
    for source in sockets.providers(Socket.NOTIFICATION_AUDIENCE).values():
        recipients |= set(await source.participant_ids(session, item_id))
    return frozenset(recipients)


async def my_teams_members(
    session: AsyncSession, team_id: uuid.UUID | None
) -> frozenset[uuid.UUID]:
    """Members of the item's team who hold a my-teams rule. Narrowed from the
    RULES side: a `teams` row has no `scope_id`, and the other direction is a
    query per candidate."""
    if team_id is None:
        return frozenset()
    opted_in = await service.team_scope_user_ids(session)
    if not opted_in:
        return frozenset()
    members = await teams.list_team_members(session, team_id)
    return frozenset(user.id for user in members if user.id in opted_in)


async def item_audience(
    session: AsyncSession,
    item_id: uuid.UUID,
    subject: Subject,
    *,
    own: frozenset[uuid.UUID] = frozenset(),
) -> Audience:
    """Everyone an ambient item notification could reach, split by relation.
    `_apply` resolves channels before `_allowed`, so `off` recipients cost no
    permission check."""
    participating = await recipient_ids(session, item_id)
    subscribers = await service.subscriber_ids(
        session, project_id=subject.project_id, team_id=subject.team_id
    )
    return Audience(
        own=own,
        participating=participating,
        in_my_teams=await my_teams_members(session, subject.team_id),
        subscribers=frozenset(subscribers),
    )


def uuid_or_none(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
    except (ValueError, TypeError, AttributeError):
        return None


def item_ref(payload: dict) -> dict:
    """The canonical item ref every item-scoped event carries (RADD-922)."""
    return payload.get("item") or {}


def subject_of(payload: dict, item: "WorkItem | None") -> Subject:
    """The item's project and team, from the ROW (where it is NOW); the payload
    only for an item since deleted."""
    if item is not None:
        return Subject(project_id=item.project_id, team_id=item.team_id)
    ref = item_ref(payload)
    return Subject(
        project_id=uuid_or_none((ref.get("project") or {}).get("id")),
        team_id=uuid_or_none((ref.get("team") or {}).get("id")),
    )


def own_of(item: "WorkItem | None", payload: dict) -> frozenset[uuid.UUID]:
    """Whose work this is: assignee and reporter (spec 118) — not the creator,
    who is `participating` by watching."""
    if item is not None:
        return frozenset(
            uid for uid in (item.assignee_id, item.reporter_id) if uid is not None
        )
    ref = item_ref(payload)
    return frozenset(
        uid
        for uid in (
            uuid_or_none((ref.get("assignee") or {}).get("id")),
            uuid_or_none((ref.get("reporter") or {}).get("id")),
        )
        if uid is not None
    )


async def actor_name_of(session: AsyncSession, event: Event) -> str | None:
    """Who did it, once per event; stored at WRITE time so a rename cannot make
    the row lie."""
    if event.actor_id is None:
        return None
    actor = (await auth.users_by_ids(session, {event.actor_id})).get(event.actor_id)
    return actor.name if actor else None
