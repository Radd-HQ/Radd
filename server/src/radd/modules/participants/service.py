"""Request participants (spec 72): users + whole teams following an item.

Participation rides the existing watcher + notify machinery, and since
RADD-844 it is also a RELATION on the item (`@participant`, registered in
__init__): the Baseline's `item.read@participant` + `comment.write@participant`
give a share the second-reporter meaning — the person opens that one item,
comments on it, and passes notify's per-row read gate — while recipients still
pass every notify filter (internal comments stay internal). Direct USER
participants are auto-watched on add (`notify.add_watchers` — one fan-out
mechanism, no parallel path); TEAM participants stay LIVE: the notify consumer
unions `team_recipient_ids` (CURRENT members at fan-out time) into the watcher
set through a deferred feature-detected seam on its side (this module loads
after notify).

The management gate is the feature's point: `item.update` OR being the item's
REPORTER — an identity check, not a permission — so a requester can share
their own ticket. Flush, never commit; cross-module via public service fns.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, ForbiddenError, NotFoundError
from radd.modules.auth import service as auth
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.modules.events import service as events
from radd.modules.items import service as items_service
from radd.modules.items.enums import ItemEntity
from radd.modules.items.models import WorkItem
from radd.modules.items.schemas import TeamRef, UserRef
from radd.modules.notify import service as notify_service
from radd.modules.teams import service as teams_service
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project

from .models import ItemParticipant
from .schemas import ItemParticipantsRead, ParticipantAdd, ParticipantRow
from .types import ParticipantEntity, ParticipantEvent


# --- the notify seam (feature-detected deferred import on notify's side) ---


async def team_recipient_ids(session: AsyncSession, item_id: uuid.UUID) -> set[uuid.UUID]:
    """CURRENT members of the item's participant teams — resolved at fan-out
    time, so joining a team joins its shared tickets and leaving stops delivery
    without cleanup rows. Deleted teams drop out via FK CASCADE."""
    result = await session.execute(
        select(ItemParticipant.team_id).where(
            ItemParticipant.item_id == item_id, ItemParticipant.team_id.is_not(None)
        )
    )
    recipients: set[uuid.UUID] = set()
    for team_id in result.scalars():
        members = await teams_service.list_team_members(session, team_id)
        recipients.update(member.id for member in members)
    return recipients


# --- helpers ---


async def _item_project(
    session: AsyncSession, item_id: uuid.UUID, actor: User
) -> tuple[WorkItem, Project, frozenset[Permission]]:
    # RADD-823: THE item seam — participants inherit per-item read rules.
    return await items_service.require_readable_item(session, item_id, actor)


def _can_manage(
    permissions: frozenset[Permission], actor: User, item: WorkItem
) -> bool:
    """item.update OR the item's REPORTER (identity, not permission — spec 72's
    point: a requester shares their own ticket)."""
    return Permission.ITEM_UPDATE in permissions or actor.id == item.reporter_id


def _user_ref(user: User | None) -> UserRef | None:
    if user is None:
        return None
    return UserRef(
        id=user.id,
        name=user.name,
        avatar_color=user.avatar_color,
        avatar_emoji=user.avatar_emoji,
    )


async def _rows(session: AsyncSession, item_id: uuid.UUID) -> list[ItemParticipant]:
    result = await session.execute(
        select(ItemParticipant)
        .where(ItemParticipant.item_id == item_id)
        .order_by(ItemParticipant.created_at, ItemParticipant.id)
    )
    return list(result.scalars())


async def _reads(
    session: AsyncSession, rows: list[ItemParticipant]
) -> list[ParticipantRow]:
    user_ids = {row.user_id for row in rows if row.user_id}
    user_ids |= {row.added_by for row in rows if row.added_by}
    users = await auth.users_by_ids(session, user_ids)
    teams = await teams_service.teams_by_ids(
        session, {row.team_id for row in rows if row.team_id}
    )
    reads: list[ParticipantRow] = []
    for row in rows:
        team = teams.get(row.team_id) if row.team_id else None
        reads.append(
            ParticipantRow(
                id=row.id,
                user=_user_ref(users.get(row.user_id) if row.user_id else None),
                team=TeamRef(id=team.id, name=team.name) if team else None,
                added_by=_user_ref(users.get(row.added_by) if row.added_by else None),
                created_at=row.created_at,
            )
        )
    return reads


async def _emit(
    session: AsyncSession,
    event_type: ParticipantEvent,
    item: WorkItem,
    project: Project,
    actor: User,
    read: ParticipantRow,
) -> None:
    """Entity ITEM (csat/approvals precedent): History feed, realtime item
    invalidation, and item-scoped automations — no RELATED_EVENT_TYPES entry."""
    await events.emit(
        session,
        event_type=event_type,
        entity_type=ItemEntity.ITEM,
        entity_id=item.id,
        actor_id=actor.id,
        subjects={"item": item.id},
        payload={
            "user": {"id": str(read.user.id), "name": read.user.name} if read.user else None,
            "team": {"id": str(read.team.id), "name": read.team.name} if read.team else None,
            # Scalar display name for the History one-liner (`_DETAIL_KEYS`).
            "participant": read.user.name if read.user else read.team.name if read.team else "?",
        },
    )


# --- API surface ---


async def list_participants(
    session: AsyncSession, item_id: uuid.UUID, actor: User
) -> ItemParticipantsRead:
    item, project, permissions = await _item_project(session, item_id, actor)
    reads = await _reads(session, await _rows(session, item_id))
    return ItemParticipantsRead(
        users=[read.user for read in reads if read.user],
        teams=[read.team for read in reads if read.team],
        rows=reads,
        can_manage=_can_manage(permissions, actor, item),
    )


async def add_participant(
    session: AsyncSession, item_id: uuid.UUID, data: ParticipantAdd, actor: User
) -> ParticipantRow:
    item, project, permissions = await _item_project(session, item_id, actor)
    if not _can_manage(permissions, actor, item):
        raise ForbiddenError(
            "adding participants requires item.update or being the item's reporter"
        )
    if data.user_id is not None:
        await _validate_user_subject(session, data.user_id)
        dupe = ItemParticipant.user_id == data.user_id
    else:
        await _validate_team_subject(session, data.team_id)
        dupe = ItemParticipant.team_id == data.team_id
    existing = await session.scalar(
        select(ItemParticipant.id).where(ItemParticipant.item_id == item.id, dupe)
    )
    if existing is not None:
        raise ConflictError(
            ParticipantEntity.PARTICIPANT, reason="already a participant on this item"
        )
    row = ItemParticipant(
        item_id=item.id, user_id=data.user_id, team_id=data.team_id, added_by=actor.id
    )
    session.add(row)
    await session.flush()
    if data.user_id is not None:
        # Auto-watch (spec 72 §3): the direct participant rides the ordinary
        # watcher fan-out — one mechanism, no parallel path. Idempotent.
        await notify_service.add_watchers(session, item.id, [data.user_id])
    read = (await _reads(session, [row]))[0]
    await _emit(session, ParticipantEvent.ADDED, item, project, actor, read)
    return read


async def remove_participant(
    session: AsyncSession, item_id: uuid.UUID, participant_id: uuid.UUID, actor: User
) -> None:
    # Self-leave is an IDENTITY operation (RADD-844): removing yourself from a
    # thing — to stop being listed and notified — must not require being able
    # to SEE it, or a participant who lost project access is trapped on the
    # roster forever. The row is loaded first; only a non-self removal walks
    # through the readability gate.
    row = await session.get(ItemParticipant, participant_id)
    if row is None or row.item_id != item_id:
        raise NotFoundError(ParticipantEntity.PARTICIPANT, participant_id)
    is_self_leave = row.user_id is not None and row.user_id == actor.id
    if is_self_leave:
        item = await items_service.require_item(session, item_id)
        project = await projects_service.get_project(session, item.project_id)
    else:
        item, project, permissions = await _item_project(session, item_id, actor)
        if not _can_manage(permissions, actor, item):
            raise ForbiddenError(
                "removing participants requires item.update or being the item's reporter"
            )
    read = (await _reads(session, [row]))[0]
    await session.delete(row)
    await session.flush()
    await _emit(session, ParticipantEvent.REMOVED, item, project, actor, read)


# --- subject validation (approvals rule-write precedent — all 409) ---


async def _validate_user_subject(
    session: AsyncSession, user_id: uuid.UUID
) -> None:
    """Exists + active (any active user holds the global member floor — spec 86)
    — participation is for INTERNAL users (spec 72)."""
    users = await auth.users_by_ids(session, {user_id})
    user = users.get(user_id)
    if user is None or not user.active:
        raise ConflictError(
            ParticipantEntity.PARTICIPANT, reason=f"unknown or inactive user {user_id}"
        )


async def _validate_team_subject(
    session: AsyncSession, team_id: uuid.UUID | None
) -> None:
    assert team_id is not None  # schema-enforced (exactly one subject)
    teams = await teams_service.teams_by_ids(session, {team_id})
    if teams.get(team_id) is None:
        raise ConflictError(
            ParticipantEntity.PARTICIPANT,
            reason=f"team {team_id} does not exist",
        )


async def projects_with_participation(session: AsyncSession, user) -> set[uuid.UUID]:
    """Projects holding an item this actor is a PARTICIPANT on (RADD-937).

    Direct rows and team rows alike: a team participant row stays live (the
    notify consumer resolves current membership at fan-out), so visibility
    resolves the same way rather than snapshotting who was on the team when the
    row was written.

    Contributed to the kernel's project-relation registry so the visibility
    resolver never learns that participants exist.
    """
    from radd.modules.teams import service as teams  # deferred: teams loads first

    team_ids = await teams.user_team_ids(session, user.id)
    condition = ItemParticipant.user_id == user.id
    if team_ids:
        condition = condition | ItemParticipant.team_id.in_(team_ids)
    rows = await session.execute(
        select(WorkItem.project_id)
        .join(ItemParticipant, ItemParticipant.item_id == WorkItem.id)
        .where(condition)
        .distinct()
    )
    return set(rows.scalars())
