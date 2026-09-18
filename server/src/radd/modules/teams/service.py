import uuid
from collections.abc import Iterable

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import ilike_term
from radd.exceptions import ConflictError, NotFoundError
from radd.modules.auth import service as auth
from radd.modules.auth.models import User
from radd.kernel import changes
from radd.modules.events import service as events
from radd.modules.groups import service as groups_service
from radd.modules.groups.service import Group

from .models import Team, TeamManager, TeamMember
from .options import list_options as list_options, reference_options as reference_options
from .reading import (candidate_page as candidate_page, member_page as member_page,
                      member_projection, member_counts as member_counts, stewardship_page as stewardship_page,
                      steward_candidates as steward_candidates, group_page as group_page)
from .schemas import TeamCreate, TeamUpdate
from .types import TeamChange, TeamEntity, TeamEvent


async def create_team(
    session: AsyncSession, data: TeamCreate, actor_id: uuid.UUID | None = None
) -> Team:
    existing = await session.scalar(select(Team.id).where(Team.name == data.name))
    if existing:
        raise ConflictError(TeamEntity.TEAM, data.name)
    # Spec 87: the creator owns the team, so an admin creating one on someone's
    # behalf hands it over with POST /teams/{id}/transfer rather than staying
    # the bottleneck. An explicit owner is validated — the FK would otherwise
    # answer an unknown id with a 500.
    if data.owner_id is not None:
        await auth.get_user(session, data.owner_id)
    team = Team(name=data.name, owner_id=data.owner_id or actor_id)
    session.add(team)
    await session.flush()
    await events.emit(
        session,
        event_type=TeamEvent.CREATED,
        entity_type=TeamEntity.TEAM,
        entity_id=team.id,
        actor_id=actor_id,
        payload={"name": team.name, "owner_id": str(team.owner_id) if team.owner_id else None},
    )
    return team


async def list_teams(
    session: AsyncSession,
    *,
    q: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[Team]:
    stmt = select(Team).order_by(Team.name, Team.id)
    if q and q.strip():
        stmt = stmt.where(Team.name.ilike(ilike_term(q.strip())))
    if limit is not None:
        stmt = stmt.offset(offset).limit(limit)
    return list((await session.execute(stmt)).scalars())


async def count_teams(session: AsyncSession, *, q: str | None = None) -> int:
    stmt = select(func.count()).select_from(Team)
    if q and q.strip():
        stmt = stmt.where(Team.name.ilike(ilike_term(q.strip())))
    return (await session.execute(stmt)).scalar_one()


async def get_team(session: AsyncSession, team_id: uuid.UUID, *, for_update: bool = False) -> Team:
    if for_update:
        team = await session.scalar(select(Team).where(Team.id == team_id).with_for_update()
                                    .execution_options(populate_existing=True))
    else:
        team = await session.get(Team, team_id)
    if team is None:
        raise NotFoundError(TeamEntity.TEAM, team_id)
    return team


async def teams_by_ids(session: AsyncSession, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, Team]:
    result = await session.execute(select(Team).where(Team.id.in_(set(ids))))
    return {team.id: team for team in result.scalars()}


async def update_team(
    session: AsyncSession, team_id: uuid.UUID, data: TeamUpdate, actor_id: uuid.UUID | None = None
) -> Team:
    """PATCH /teams/{id}: rename. (RADD-829 retired the AD-link branch — the
    directory's truth is a Group, held as a member.)"""
    team = await get_team(session, team_id)
    if data.name is not None and data.name != team.name:
        existing = await session.scalar(
            select(Team.id).where(Team.name == data.name, Team.id != team.id)
        )
        if existing:
            raise ConflictError(TeamEntity.TEAM, data.name)
        previous = team.name
        team.name = data.name
        await session.flush()
        await _emit_updated(
            session,
            team,
            actor_id,
            {"action": TeamChange.RENAMED, "name": team.name},
            [{"field": "name", "from": previous, "to": team.name}],
        )
    return team


async def delete_team(
    session: AsyncSession, team_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> None:
    """Delete a team (spec 87 — the team.delete atom had no endpoint).

    Refused while the team still grants access to a project: dropping it would
    silently revoke everyone on it, and the project's access list is the place to
    make that decision. Also refused while items are assigned to it —
    `work_items.team_id` is RESTRICT, so asking first turns what would be a 500
    into an answer that says what to do. Members, managers and any instance-wide
    grants held by the team go with it (FK CASCADE).

    RADD-929: the project count comes from the team's project-scoped ROLE GRANTS.
    It used to count `project_teams` rows, which stopped being the whole answer
    the moment a team could also be entitled by a grant — a team holding a
    project only by grant deleted silently.
    """
    team = await get_team(session, team_id)
    from radd.modules.auth import grants as auth_grants  # deferred: auth loads first

    attached = len(
        {
            grant.project_id
            for grant in await auth_grants.grants_for_subject(session, team_id=team_id)
            if grant.project_id is not None
        }
    )
    if attached:
        raise ConflictError(
            TeamEntity.TEAM,
            reason=(
                f"'{team.name}' still grants access to {attached} project(s) — revoke those "
                "roles first so the access loss is deliberate"
            ),
        )
    # Deferred import: items loads after teams — a public service call, not a
    # reach into the items tables (the authz -> teams idiom).
    from radd.modules.items import service as items_service

    assigned = await items_service.count_items_assigned_to_team(session, team_id)
    if assigned:
        raise ConflictError(
            TeamEntity.TEAM,
            reason=f"{assigned} item(s) are still assigned to '{team.name}' — reassign them first",
        )
    await events.emit(
        session,
        event_type=TeamEvent.DELETED,
        entity_type=TeamEntity.TEAM,
        entity_id=team.id,
        actor_id=actor_id,
        payload={"name": team.name},
    )
    await session.delete(team)
    await session.flush()


# --- team members (RADD-829: a member is a USER or a GROUP) --------------------


async def add_team_member(
    session: AsyncSession, team_id: uuid.UUID, user_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> User:
    team = await get_team(session, team_id)
    user = await auth.get_user(session, user_id)
    existing = await session.scalar(
        select(TeamMember.id).where(
            TeamMember.team_id == team_id, TeamMember.user_id == user_id
        )
    )
    if existing:
        raise ConflictError(TeamEntity.MEMBER, user_id)
    session.add(TeamMember(team_id=team_id, user_id=user_id))
    await session.flush()
    forget_user_teams(session)
    await _emit_updated(
        session,
        team,
        actor_id,
        {"action": TeamChange.MEMBER_ADDED, "user_id": str(user_id)},
        [{"field": "members", "added": [user.name], "removed": []}],
    )
    return user


async def remove_team_member(
    session: AsyncSession, team_id: uuid.UUID, user_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> None:
    team = await get_team(session, team_id)
    result = await session.execute(
        delete(TeamMember).where(TeamMember.team_id == team_id, TeamMember.user_id == user_id)
    )
    if result.rowcount == 0:
        raise NotFoundError(TeamEntity.MEMBER, user_id)
    forget_user_teams(session)
    await _emit_updated(
        session,
        team,
        actor_id,
        {"action": TeamChange.MEMBER_REMOVED, "user_id": str(user_id)},
        [{"field": "members", "added": [], "removed": await _user_names(session, [user_id])}],
    )


async def add_team_group(
    session: AsyncSession, team_id: uuid.UUID, group_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> Group:
    """The team gains a directory GROUP as a member (RADD-829): its people —
    nesting included — count as team members everywhere membership is asked."""
    team = await get_team(session, team_id)
    group = await groups_service.get_group(session, group_id)
    existing = await session.scalar(
        select(TeamMember.id).where(
            TeamMember.team_id == team_id, TeamMember.group_id == group_id
        )
    )
    if existing:
        raise ConflictError(TeamEntity.MEMBER, group_id)
    session.add(TeamMember(team_id=team_id, group_id=group_id))
    await session.flush()
    forget_user_teams(session)
    await _emit_updated(
        session,
        team,
        actor_id,
        {"action": TeamChange.GROUP_ADDED, "group_id": str(group_id), "group": group.name},
        [{"field": "members", "added": [f"group {group.name}"], "removed": []}],
    )
    return group


async def remove_team_group(
    session: AsyncSession, team_id: uuid.UUID, group_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> None:
    team = await get_team(session, team_id)
    group = await groups_service.get_group(session, group_id)
    result = await session.execute(
        delete(TeamMember).where(
            TeamMember.team_id == team_id, TeamMember.group_id == group_id
        )
    )
    if result.rowcount == 0:
        raise NotFoundError(TeamEntity.MEMBER, group_id)
    forget_user_teams(session)
    await _emit_updated(
        session,
        team,
        actor_id,
        {"action": TeamChange.GROUP_REMOVED, "group_id": str(group_id), "group": group.name},
        [{"field": "members", "added": [], "removed": [f"group {group.name}"]}],
    )


async def team_groups(session: AsyncSession, team_id: uuid.UUID) -> list[Group]:
    """The team's GROUP members (RADD-829)."""
    await get_team(session, team_id)
    result = await session.execute(
        select(Group)
        .join(TeamMember, TeamMember.group_id == Group.id)
        .where(TeamMember.team_id == team_id)
        .order_by(Group.name)
    )
    return list(result.scalars())


async def list_team_members(session: AsyncSession, team_id: uuid.UUID) -> list[User]:
    """Every PERSON on the team: direct user rows plus the people its member
    groups resolve to, nesting included. Group-expanded members count as
    members — post-migration a directory team's people are reachable ONLY via
    its group, so stewardship, leave and approval electorates all depend on
    this expansion."""
    users = await member_users_with_via(session, team_id)
    return sorted({u.id: u for u, _via in users}.values(), key=lambda u: u.name)


async def member_users_with_via(
    session: AsyncSession, team_id: uuid.UUID
) -> list[tuple[User, str | None]]:
    """(user, via-group-name|None) pairs — the router's member list with
    provenance. A person reached both directly and via a group appears once,
    as direct."""
    await get_team(session, team_id)
    members = member_projection(team_id).subquery()
    rows = await session.execute(select(User, members.c.via_group)
                                 .join(members, members.c.user_id == User.id)
                                 .order_by(User.name, User.id))
    return [(user, via) for user, via in rows]


async def users_for_teams(session: AsyncSession, team_ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
    """Effective membership union in one query, including nested groups."""
    ids = list(set(team_ids))
    if not ids:
        return set()
    members = member_projection(ids).subquery()
    return set(await session.scalars(select(members.c.user_id)))


# --- ownership + delegated management (spec 87) ---


async def managers_by_team_ids(session: AsyncSession, team_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, list[uuid.UUID]]:
    """One manager query for the requested window; no per-team steward lookup."""
    ids = set(team_ids)
    if not ids:
        return {}
    rows = await session.execute(select(TeamManager.team_id, TeamManager.user_id)
                                 .where(TeamManager.team_id.in_(ids)).order_by(TeamManager.user_id))
    result: dict[uuid.UUID, list[uuid.UUID]] = {identifier: [] for identifier in ids}
    for team_id, user_id in rows:
        result[team_id].append(user_id)
    return result


async def list_managers(session: AsyncSession, team_id: uuid.UUID) -> list[uuid.UUID]:
    result = await session.execute(
        select(TeamManager.user_id).where(TeamManager.team_id == team_id)
    )
    return list(result.scalars())


async def stewards_any_team(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """Does this person own or manage at least one team (spec 87)? The SPA gates
    the Teams settings nav on it — a team leader holds no global team atom, so
    without this the page they are meant to use would be invisible to them."""
    owned = await session.scalar(select(Team.id).where(Team.owner_id == user_id).limit(1))
    if owned:
        return True
    managed = await session.scalar(
        select(TeamManager.team_id).where(TeamManager.user_id == user_id).limit(1)
    )
    return managed is not None


async def is_team_steward(session: AsyncSession, user_id: uuid.UUID, team: Team) -> bool:
    """Does this person administer THIS team in their own right — as its owner or
    one of its managers? Callers combine this with the global `team.update` atom;
    keeping the two separate is what lets a team leader manage one team without
    being handed every team."""
    if team.owner_id == user_id:
        return True
    return await session.get(TeamManager, (team.id, user_id)) is not None


async def replace_managers(
    session: AsyncSession,
    team_id: uuid.UUID,
    user_ids: Iterable[uuid.UUID],
    actor_id: uuid.UUID | None = None,
) -> list[uuid.UUID]:
    """Full-state replace of the team's managers (the `PUT /views/{id}/sharing`
    idiom). Managers need not be members — a lead can run a team they are not on."""
    team = await get_team(session, team_id, for_update=True)
    wanted = list(dict.fromkeys(user_ids))
    found = await auth.users_by_ids(session, wanted)
    for user_id in wanted:
        if user_id not in found:
            raise ConflictError(TeamEntity.MANAGER, reason=f"no such user {user_id}")
    previous = await _user_names(session, await list_managers(session, team_id))
    await session.execute(delete(TeamManager).where(TeamManager.team_id == team_id))
    for user_id in wanted:
        session.add(TeamManager(team_id=team_id, user_id=user_id))
    await session.flush()
    await _emit_updated(
        session,
        team,
        actor_id,
        {"action": TeamChange.MANAGERS_REPLACED, "user_ids": [str(u) for u in wanted]},
        _collection("managers", previous, [found[u].name for u in wanted]),
    )
    return wanted


async def add_manager(session: AsyncSession, team_id: uuid.UUID, user_id: uuid.UUID,
                      actor_id: uuid.UUID | None = None) -> None:
    team = await get_team(session, team_id, for_update=True)
    target = await auth.get_user(session, user_id)
    if not target.active or user_id == team.owner_id:
        raise ConflictError(TeamEntity.MANAGER, reason="Choose an active person other than the owner")
    if await session.get(TeamManager, (team_id, user_id)):
        return
    count = await session.scalar(select(func.count()).select_from(TeamManager).where(TeamManager.team_id == team_id))
    if count >= 50:
        raise ConflictError(TeamEntity.MANAGER, reason="A team may appoint up to 50 managers")
    session.add(TeamManager(team_id=team_id, user_id=user_id))
    await session.flush()
    await _emit_updated(
        session,
        team,
        actor_id,
        {
            "action": TeamChange.MANAGERS_REPLACED,
            "user_ids": [str(value) for value in await list_managers(session, team_id)],
        },
        [{"field": "managers", "added": [target.name], "removed": []}],
    )


async def remove_manager(session: AsyncSession, team_id: uuid.UUID, user_id: uuid.UUID,
                         actor_id: uuid.UUID | None = None) -> None:
    team = await get_team(session, team_id, for_update=True)
    result = await session.execute(delete(TeamManager).where(TeamManager.team_id == team_id,
                                                            TeamManager.user_id == user_id))
    if not result.rowcount:
        raise NotFoundError(TeamEntity.MANAGER, user_id)
    await _emit_updated(
        session,
        team,
        actor_id,
        {
            "action": TeamChange.MANAGERS_REPLACED,
            "user_ids": [str(value) for value in await list_managers(session, team_id)],
        },
        [{"field": "managers", "added": [], "removed": await _user_names(session, [user_id])}],
    )


async def transfer_ownership(
    session: AsyncSession, team_id: uuid.UUID, user_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> Team:
    """Reassign `owner_id`. The target must be an active user — handing a team to
    a deactivated account would leave it administrable only by the atom holders.
    The previous owner stays on as a manager, so a transfer never locks anyone out
    by accident (the new owner can revoke)."""
    team = await get_team(session, team_id, for_update=True)
    target = await auth.get_user(session, user_id)
    if not target.active:
        raise ConflictError(
            TeamEntity.TEAM, reason=f"{target.email} is deactivated and cannot own a team"
        )
    previous_owner_id = team.owner_id
    team.owner_id = target.id
    if previous_owner_id and previous_owner_id != target.id:
        if not await session.get(TeamManager, (team.id, previous_owner_id)):
            session.add(TeamManager(team_id=team.id, user_id=previous_owner_id))
    # A now-redundant manager row for the new owner is dropped (ownership subsumes it).
    await session.execute(
        delete(TeamManager).where(
            TeamManager.team_id == team.id, TeamManager.user_id == target.id
        )
    )
    await session.flush()
    previous_name = (
        (await _user_names(session, [previous_owner_id]) or [None])[0] if previous_owner_id else None
    )
    await _emit_updated(
        session,
        team,
        actor_id,
        {"action": TeamChange.OWNER_TRANSFERRED, "owner_id": str(target.id)},
        [{"field": "owner", "from": previous_name, "to": target.name}],
    )
    return team


# --- helpers other modules import (the authz engine + spec 07 build on these) ---


async def _membership_filter(session: AsyncSession, user_id: uuid.UUID):
    """The team_members condition for one person (RADD-829): a direct user row,
    OR a group row for any group they belong to transitively. THE subject-graph
    join — every resolution below goes through it, so the group swap happened
    in exactly one place."""
    group_ids = await groups_service.user_group_ids(session, user_id)
    condition = TeamMember.user_id == user_id
    if group_ids:
        condition = or_(condition, TeamMember.group_id.in_(group_ids))
    return condition


async def teams_for_user(session: AsyncSession, user_id: uuid.UUID) -> list[Team]:
    result = await session.execute(
        select(Team)
        .join(TeamMember, TeamMember.team_id == Team.id)
        .where(await _membership_filter(session, user_id))
        .order_by(Team.name)
        .distinct()
    )
    return list(result.scalars())


#: Per-request memo key prefix (RADD-830): 20 call sites resolve membership
#: through this seam, and a batched permission resolution hits it repeatedly.
_USER_TEAMS_CACHE_KEY = "radd.user_team_ids"


def forget_user_teams(session: AsyncSession) -> None:
    """Drop every memoised membership — call after a team_members write (the
    `forget_baseline` rule: the request that changes the graph must not answer
    with the sets it read before)."""
    for key in [k for k in session.info if str(k).startswith(_USER_TEAMS_CACHE_KEY)]:
        session.info.pop(key, None)


async def user_team_ids(session: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    """THE membership seam (20 call sites): the teams this person is on, direct
    rows and group-carried alike. Memoised per request (RADD-830) beside
    `baseline_permissions` — the group closure underneath is a graph walk."""
    key = f"{_USER_TEAMS_CACHE_KEY}:{user_id}"
    cached: set[uuid.UUID] | None = session.info.get(key)
    if cached is not None:
        return cached
    result = await session.execute(
        select(TeamMember.team_id).where(await _membership_filter(session, user_id))
    )
    resolved = set(result.scalars())
    session.info[key] = resolved
    return resolved


async def _user_names(session: AsyncSession, user_ids) -> list[str]:
    """Display names for a diff (spec 123) — a missing row keeps its id."""
    ids = list(user_ids)
    found = await auth.users_by_ids(session, ids)
    return [found[u].name if u in found else str(u) for u in ids]


def _collection(field: str, before: list[str], after: list[str]) -> list[dict]:
    entry = changes.collection_change(field, before, after)
    return [entry] if entry is not None else []


async def _emit_updated(
    session: AsyncSession,
    team: Team,
    actor_id: uuid.UUID | None,
    payload: dict,
    diff: list[dict] | None = None,
) -> None:
    await events.emit(
        session,
        event_type=TeamEvent.UPDATED,
        entity_type=TeamEntity.TEAM,
        entity_id=team.id,
        actor_id=actor_id,
        payload={"name": team.name, **payload},
        changes=diff if diff is not None else [],
    )


async def existing_ids(session: AsyncSession, ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
    """Validate explicit relationship targets without reading the entire registry."""
    wanted = set(ids)
    if not wanted:
        return set()
    return set(await session.scalars(select(Team.id).where(Team.id.in_(wanted))))
