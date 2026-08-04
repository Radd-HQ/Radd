"""Directory-group reads, sync writes, and the transitive closures (RADD-829).

The two closures are the load-bearing pieces: membership of a nested group
means membership of every ANCESTOR (a parent group contains its child's
members), and a grant on a parent reaches every descendant's people. Both
walks are iterative id-frontiers — one query per depth level, the rollup
idiom — with a cycle guard (AD is a graph; a cycle is rare but legal) and a
depth limit, on day one. A truncated walk resolves FEWER memberships, i.e. it
fails CLOSED — the same rule `authz.baseline_permissions` states for an
absent baseline.
"""

import logging
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.exceptions import NotFoundError
from radd.modules.events import service as events

from .models import Group, GroupMember, GroupParent
from .types import GroupEntity, GroupEvent

logger = logging.getLogger(__name__)


# --- reads --------------------------------------------------------------------


async def list_groups(session: AsyncSession) -> list[Group]:
    return list((await session.execute(select(Group).order_by(Group.name))).scalars())


async def get_group(session: AsyncSession, group_id: uuid.UUID) -> Group:
    group = await session.get(Group, group_id)
    if group is None:
        raise NotFoundError(GroupEntity.GROUP, group_id)
    return group


async def groups_by_ids(
    session: AsyncSession, ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, Group]:
    result = await session.execute(select(Group).where(Group.id.in_(set(ids))))
    return {group.id: group for group in result.scalars()}


async def group_by_dn(session: AsyncSession, dn: str) -> Group | None:
    return await session.scalar(select(Group).where(Group.dn == dn))


async def direct_member_counts(
    session: AsyncSession, group_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, int]:
    from sqlalchemy import func

    rows = await session.execute(
        select(GroupMember.group_id, func.count())
        .where(GroupMember.group_id.in_(set(group_ids)))
        .group_by(GroupMember.group_id)
    )
    return dict(rows.all())


# --- the closures -------------------------------------------------------------


async def user_group_ids(session: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    """Every group the user belongs to, TRANSITIVELY: direct memberships plus
    all ancestors (a parent group contains its child groups' members). The
    upward closure behind `teams.user_team_ids` and the subject graph."""
    direct = set(
        (
            await session.execute(
                select(GroupMember.group_id).where(GroupMember.user_id == user_id)
            )
        ).scalars()
    )
    return await _ancestors_closure(session, direct)


async def _ancestors_closure(
    session: AsyncSession, seed: set[uuid.UUID]
) -> set[uuid.UUID]:
    """seed ∪ every ancestor, frontier-walked with a cycle guard + depth limit.
    Truncation fails CLOSED (fewer memberships resolved, never more)."""
    seen = set(seed)
    frontier = set(seed)
    for _ in range(settings.group_nesting_max_depth):
        if not frontier:
            break
        parents = set(
            (
                await session.execute(
                    select(GroupParent.parent_id).where(GroupParent.child_id.in_(frontier))
                )
            ).scalars()
        )
        frontier = parents - seen  # the cycle guard: a revisited node ends its branch
        seen |= parents
    else:
        if frontier:
            logger.warning(
                "group nesting deeper than %s levels — resolution truncated (fails closed)",
                settings.group_nesting_max_depth,
            )
    return seen


async def group_user_ids(session: AsyncSession, group_id: uuid.UUID) -> set[uuid.UUID]:
    """Every user a grant on this group REACHES: the downward closure — the
    group's own members plus every descendant's. The reverse of
    `user_group_ids`, and the third query shape the review named ("resolves to
    214 people"): the grant UI's headcount and the inspector's reach ride it."""
    seen = {group_id}
    frontier = {group_id}
    for _ in range(settings.group_nesting_max_depth):
        if not frontier:
            break
        children = set(
            (
                await session.execute(
                    select(GroupParent.child_id).where(GroupParent.parent_id.in_(frontier))
                )
            ).scalars()
        )
        frontier = children - seen
        seen |= children
    else:
        if frontier:
            logger.warning(
                "group nesting deeper than %s levels — headcount truncated",
                settings.group_nesting_max_depth,
            )
    rows = await session.execute(
        select(GroupMember.user_id).where(GroupMember.group_id.in_(seen)).distinct()
    )
    return set(rows.scalars())


async def users_for_groups(
    session: AsyncSession, group_ids: Iterable[uuid.UUID]
) -> set[uuid.UUID]:
    """Batched downward closure over several groups (team-member expansion)."""
    out: set[uuid.UUID] = set()
    for group_id in set(group_ids):
        out |= await group_user_ids(session, group_id)
    return out


# --- sync writes (the ldap module drives these) --------------------------------


async def upsert_group(session: AsyncSession, *, dn: str, name: str) -> Group:
    """Find-or-create by DN (the directory's identity); refresh the display name."""
    group = await group_by_dn(session, dn)
    if group is None:
        group = Group(dn=dn, name=name)
        session.add(group)
        await session.flush()
        return group
    if name and group.name != name:
        group.name = name
        await session.flush()
    return group


async def replace_members(
    session: AsyncSession,
    group: Group,
    user_ids: Iterable[uuid.UUID],
    *,
    allow_removals: bool = True,
) -> tuple[int, int]:
    """Set the group's DIRECT members to `user_ids` (sync owns the rows
    outright — no manual path exists). `allow_removals=False` is the spec-87
    missing-group stance: joins still apply, leavers are held."""
    desired = set(user_ids)
    current = set(
        (
            await session.execute(
                select(GroupMember.user_id).where(GroupMember.group_id == group.id)
            )
        ).scalars()
    )
    adds = desired - current
    removes = (current - desired) if allow_removals else set()
    for user_id in adds:
        session.add(GroupMember(group_id=group.id, user_id=user_id))
    if removes:
        await session.execute(
            delete(GroupMember).where(
                GroupMember.group_id == group.id, GroupMember.user_id.in_(removes)
            )
        )
    await session.flush()
    return len(adds), len(removes)


async def set_parents(
    session: AsyncSession, group: Group, parent_ids: Iterable[uuid.UUID]
) -> None:
    """Replace the group's nesting edges (child side). RADD-831 feeds this from
    the directory's memberOf answers."""
    desired = set(parent_ids) - {group.id}  # a self-edge is never meaningful
    current = set(
        (
            await session.execute(
                select(GroupParent.parent_id).where(GroupParent.child_id == group.id)
            )
        ).scalars()
    )
    for parent_id in desired - current:
        session.add(GroupParent(child_id=group.id, parent_id=parent_id))
    stale = current - desired
    if stale:
        await session.execute(
            delete(GroupParent).where(
                GroupParent.child_id == group.id, GroupParent.parent_id.in_(stale)
            )
        )
    await session.flush()


async def mark_missing(
    session: AsyncSession, group: Group, *, missing: bool
) -> None:
    """Flag/unflag a group whose DN stopped resolving (spec 87, moved here).
    Idempotent; while flagged, sync paths hold removals. Grants are KEPT — a
    directory outage must not become a permission outage."""
    already = group.directory_missing_since is not None
    if already == missing:
        return
    group.directory_missing_since = (
        datetime.now(UTC).replace(tzinfo=None) if missing else None
    )
    await session.flush()
    await events.emit(
        session,
        event_type=GroupEvent.MISSING if missing else GroupEvent.RESTORED,
        entity_type=GroupEntity.GROUP,
        entity_id=group.id,
        actor_id=None,
        payload={"dn": group.dn, "name": group.name},
    )
