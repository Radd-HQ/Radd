"""Who could hear about an item event, and HOW each of them is connected (spec 118).

The consumer's other half. `planner` decides what to say; this decides who is in
the room, split into the four sets the channel matrix's columns are about —
because a flat recipient list (which is what `recipient_ids` was on its own) is
exactly what makes "stop telling me about issues I merely watch, but keep
telling me about mine" unsayable.

Its own file rather than more of `consumer.py`: the wiki's fan-out asks the same
question about a page, the answers come from four different modules, and the
handlers that consume it read better without a hundred lines of set-building
between them.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth import service as auth
from radd.modules.events.service import Event
from radd.modules.items.models import WorkItem
from radd.modules.teams import service as teams

from . import service
from .planner import Audience
from .rules import Subject


async def recipient_ids(session: AsyncSession, item_id: uuid.UUID) -> frozenset[uuid.UUID]:
    """The PARTICIPATING set: watchers ∪ CURRENT members of the item's
    participant teams (spec 72 — resolved at fan-out time, so team joins/leaves
    take effect without cleanup rows). Deferred feature-detected import: the
    participants module loads AFTER notify and may be disabled. Every recipient
    still passes `consumer._allowed` (item.read + internal-comment filters) —
    team participation never widens what someone may see.

    This used to be the WHOLE ambient recipient set. Since spec 118 it is one of
    four: flattening them lost which set someone came out of, and that is the
    only thing the channel matrix's columns are about."""
    recipients = set(await service.watcher_ids(session, item_id))
    try:
        from radd.modules.participants import service as participants
    except ImportError:
        return frozenset(recipients)
    recipients |= await participants.team_recipient_ids(session, item_id)
    return frozenset(recipients)


async def my_teams_members(
    session: AsyncSession, team_id: uuid.UUID | None
) -> frozenset[uuid.UUID]:
    """Members of the item's team who have a my-teams rule at all.

    Narrowed from the RULES side first, not the team side. A `teams` rule row
    carries no `scope_id` — "my teams" is whatever they are today — so it cannot
    be looked up by target; the alternative direction is resolving every team of
    every candidate recipient, which is a query per person for an answer almost
    always empty. One small indexed read, and on an instance where nobody uses
    the column it costs exactly that and stops.
    """
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
    """Everyone an ambient item notification could reach, split by RELATION.

    Three queries beyond what the old flat version cost: the subscriber lookup
    (one indexed read over `ix_notification_rules_target`, matching project and
    team at once), the my-teams narrowing (skipped entirely when nobody uses the
    column), and the team member expansion behind it.

    Order of operations matters for cost, not correctness: everyone here still
    goes through `consumer._allowed`, which is per-recipient expensive, so
    `_apply` resolves each person's CHANNEL first and drops the `off` ones before
    asking the permission question about them.
    """
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
    """The canonical item ref every item-scoped event carries (RADD-922).

    The consumer used to reconstruct the issue key FOUR ways — `payload["key"]`
    for item events, `payload["item_key"]` for SLA events, and a database round
    trip for the two families that carried neither. One shape, one read."""
    return payload.get("item") or {}


def subject_of(payload: dict, item: "WorkItem | None") -> Subject:
    """What a subscription could name about this item: its project and its team.

    The ROW first, the payload second. Both are available on most paths, and the
    row is the one that is current — a subscription is matched against where the
    item is NOW, not where it was when the event was written. The payload is the
    fallback for an item that has since been deleted, which is exactly when there
    is no row to read.
    """
    if item is not None:
        return Subject(project_id=item.project_id, team_id=item.team_id)
    ref = item_ref(payload)
    return Subject(
        project_id=uuid_or_none((ref.get("project") or {}).get("id")),
        team_id=uuid_or_none((ref.get("team") or {}).get("id")),
    )


def own_of(item: "WorkItem | None", payload: dict) -> frozenset[uuid.UUID]:
    """Whose work this is: the assignee and the reporter (spec 118).

    Not "who created it" — the creator's connection to an issue is that they
    watch it, which `participating` already says. Assignee and reporter are the
    two roles that make the work THEIRS, and the two the `own` column is read as
    naming.
    """
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
    """Who did it, resolved once per event rather than per recipient. Stored on
    the notification payload at WRITE time, like every other display value, so a
    later rename cannot make the row lie about what it told you."""
    if event.actor_id is None:
        return None
    actor = (await auth.users_by_ids(session, {event.actor_id})).get(event.actor_id)
    return actor.name if actor else None
