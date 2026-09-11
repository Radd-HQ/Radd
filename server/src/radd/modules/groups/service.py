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

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import ilike_term
from radd.config import settings
from radd.exceptions import NotFoundError
from radd.modules.events import service as events

# `Group` is re-exported here as the PUBLIC group type (the events `Event`
# pattern, RADD-886/887): consumers that hold or annotate group rows — teams'
# member seam, ldap's sync — import it from the service; the ratchet test bans
# `groups.models` outside this module.
from .models import Group, GroupMember, GroupParent
from .types import GroupEntity, GroupEvent
from .reading import member_projection as member_projection
from radd.clock import utcnow

__all__ = ["Group"]  # re-exported public seam (see above)

logger = logging.getLogger(__name__)


# --- reads --------------------------------------------------------------------


async def list_groups(
    session: AsyncSession,
    *,
    q: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[Group]:
    stmt = select(Group).order_by(Group.name, Group.id)
    if q and q.strip():
        stmt = stmt.where(Group.name.ilike(ilike_term(q.strip())) | Group.dn.ilike(ilike_term(q.strip())))
    if limit is not None:
        stmt = stmt.offset(offset).limit(limit)
    return list((await session.execute(stmt)).scalars())


async def count_groups(session: AsyncSession, *, q: str | None = None) -> int:
    stmt = select(func.count()).select_from(Group)
    if q and q.strip():
        stmt = stmt.where(Group.name.ilike(ilike_term(q.strip())) | Group.dn.ilike(ilike_term(q.strip())))
    return (await session.execute(stmt)).scalar_one()


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


async def groups_by_dns(session: AsyncSession, dns: Iterable[str]) -> dict[str, Group]:
    """{dn: group} for the DNs that are mirrored — the edge sync's join
    (RADD-831): an edge is only representable between two mirrored groups."""
    wanted = {dn for dn in dns if dn}
    if not wanted:
        return {}
    result = await session.execute(select(Group).where(Group.dn.in_(wanted)))
    return {group.dn: group for group in result.scalars()}


async def member_ids(session: AsyncSession, group_id: uuid.UUID) -> set[uuid.UUID]:
    """The group's DIRECT member user-ids — NOT the transitive closure (that is
    `group_user_ids`). Consumed by ldap.groupsync's login-time join/leave
    (RADD-887), which edits one user against the group's current direct set."""
    rows = await session.execute(
        select(GroupMember.user_id).where(GroupMember.group_id == group_id)
    )
    return set(rows.scalars())


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


async def transitive_member_counts(session: AsyncSession, group_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, int]:
    """One SQL aggregation for a window of group roots, without user hydration."""
    ids = set(group_ids)
    if not ids:
        return {}
    members = member_projection(select(Group.id).where(Group.id.in_(ids))).subquery()
    rows = await session.execute(select(members.c.root_id, func.count()).group_by(members.c.root_id))
    return dict(rows.all())


# --- the closures -------------------------------------------------------------


#: Per-request memo key prefix (RADD-830): the closure runs on the hottest path
#: — a batched permission resolution asks for it several times per request.
_USER_GROUPS_CACHE_KEY = "radd.user_group_ids"


def forget_user_groups(session: AsyncSession) -> None:
    """Drop every memoised closure — call after a membership/edge write, or the
    request that CHANGES the graph answers with the sets it read before (the
    `forget_baseline` rule)."""
    for key in [k for k in session.info if str(k).startswith(_USER_GROUPS_CACHE_KEY)]:
        session.info.pop(key, None)


async def user_group_ids(session: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    """Every group the user belongs to, TRANSITIVELY: direct memberships plus
    all ancestors (a parent group contains its child groups' members). The
    upward closure behind `teams.user_team_ids` and the subject graph.

    Memoised per request beside `baseline_permissions`/`readable_projects`
    (RADD-830) — done per check this is a graph walk per permission test."""
    key = f"{_USER_GROUPS_CACHE_KEY}:{user_id}"
    cached: set[uuid.UUID] | None = session.info.get(key)
    if cached is not None:
        return cached
    direct = set(
        (
            await session.execute(
                select(GroupMember.group_id).where(GroupMember.user_id == user_id)
            )
        ).scalars()
    )
    resolved = await _ancestors_closure(session, direct)
    session.info[key] = resolved
    return resolved


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


async def nesting_edges(
    session: AsyncSession, group_ids: Iterable[uuid.UUID]
) -> tuple[dict[uuid.UUID, set[uuid.UUID]], dict[uuid.UUID, set[uuid.UUID]]]:
    """({child: parents}, {parent: children}) over the given groups — one query,
    feeds the admin screen's nesting columns (RADD-833)."""
    ids = set(group_ids)
    parents: dict[uuid.UUID, set[uuid.UUID]] = {}
    children: dict[uuid.UUID, set[uuid.UUID]] = {}
    if not ids:
        return parents, children
    rows = await session.execute(
        select(GroupParent.child_id, GroupParent.parent_id).where(
            GroupParent.child_id.in_(ids) | GroupParent.parent_id.in_(ids)
        )
    )
    for child_id, parent_id in rows.all():
        parents.setdefault(child_id, set()).add(parent_id)
        children.setdefault(parent_id, set()).add(child_id)
    return parents, children


async def membership_path(
    session: AsyncSession, user_id: uuid.UUID, group_id: uuid.UUID
) -> list[Group]:
    """The CHAIN from a granted group DOWN to the user's direct membership
    (RADD-833): [granted, …, direct]. Empty when the user is a DIRECT member
    (no chain worth showing) or not a member at all. BFS down the child edges,
    depth-limited like the closures; the first direct-membership hit wins, so
    the shortest chain is what the inspector reads."""
    direct = set(
        (
            await session.execute(
                select(GroupMember.group_id).where(GroupMember.user_id == user_id)
            )
        ).scalars()
    )
    if group_id in direct:
        return []
    paths: dict[uuid.UUID, list[uuid.UUID]] = {group_id: [group_id]}
    frontier = {group_id}
    for _ in range(settings.group_nesting_max_depth):
        if not frontier:
            break
        rows = await session.execute(
            select(GroupParent.parent_id, GroupParent.child_id).where(
                GroupParent.parent_id.in_(frontier)
            )
        )
        next_frontier: set[uuid.UUID] = set()
        for parent_id, child_id in rows.all():
            if child_id in paths:
                continue  # cycle guard / already reached shorter
            paths[child_id] = paths[parent_id] + [child_id]
            if child_id in direct:
                found = paths[child_id]
                groups = await groups_by_ids(session, found)
                return [groups[gid] for gid in found if gid in groups]
            next_frontier.add(child_id)
        frontier = next_frontier
    return []


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
    if adds or removes:
        forget_user_groups(session)
        from radd.modules.teams import service as teams  # deferred: teams loads after groups

        teams.forget_user_teams(session)
        # Every membership write funnels through here (periodic reconcile,
        # login join/leave, import), so this is the one honest place the
        # registered `group.synced` trigger can fire — and only on actual
        # change, never as a no-op heartbeat (RADD-874).
        await events.emit(
            session,
            event_type=GroupEvent.SYNCED,
            entity_type=GroupEntity.GROUP,
            entity_id=group.id,
            actor_id=None,
            payload={
                "dn": group.dn,
                "name": group.name,
                "added": len(adds),
                "removed": len(removes),
            },
        )
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
    if (desired - current) or stale:
        forget_user_groups(session)
        from radd.modules.teams import service as teams  # deferred: teams loads after groups

        teams.forget_user_teams(session)


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
        utcnow() if missing else None
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
