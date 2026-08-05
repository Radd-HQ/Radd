import uuid
from collections.abc import Iterable

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import ilike_term
from radd.exceptions import ConflictError, NotFoundError
from radd.modules.auth import roles as auth_roles, service as auth
from radd.modules.auth.models import User
from radd.modules.auth.types import BuiltinRoleKey
from radd.modules.events import service as events
from radd.modules.groups import service as groups_service
from radd.modules.groups.service import Group
from radd.modules.projects import service as projects_service

from .models import ProjectTeam, Team, TeamManager, TeamMember
from .schemas import ProjectTeamAttach, ProjectTeamUpdate, TeamCreate, TeamUpdate
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
    stmt = select(Team).order_by(Team.name)
    if q:
        stmt = stmt.where(Team.name.ilike(ilike_term(q)))
    if limit is not None:
        stmt = stmt.offset(offset).limit(limit)
    return list((await session.execute(stmt)).scalars())


async def count_teams(session: AsyncSession, *, q: str | None = None) -> int:
    stmt = select(func.count()).select_from(Team)
    if q:
        stmt = stmt.where(Team.name.ilike(ilike_term(q)))
    return (await session.execute(stmt)).scalar_one()


async def get_team(session: AsyncSession, team_id: uuid.UUID) -> Team:
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
        team.name = data.name
        await session.flush()
        await _emit_updated(
            session, team, actor_id, {"action": TeamChange.RENAMED, "name": team.name}
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
    """
    team = await get_team(session, team_id)
    attached = await session.scalar(
        select(func.count()).select_from(ProjectTeam).where(ProjectTeam.team_id == team_id)
    )
    if attached:
        raise ConflictError(
            TeamEntity.TEAM,
            reason=(
                f"'{team.name}' still grants access to {attached} project(s) — detach it there "
                "first so the access loss is deliberate"
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
        session, team, actor_id, {"action": TeamChange.MEMBER_ADDED, "user_id": str(user_id)}
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
        session, team, actor_id, {"action": TeamChange.MEMBER_REMOVED, "user_id": str(user_id)}
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
    direct_ids = list(
        (
            await session.execute(
                select(TeamMember.user_id).where(
                    TeamMember.team_id == team_id, TeamMember.user_id.is_not(None)
                )
            )
        ).scalars()
    )
    out: dict[uuid.UUID, tuple[User, str | None]] = {}
    users = await auth.users_by_ids(session, direct_ids)
    for user in users.values():
        out[user.id] = (user, None)
    for group in await team_groups(session, team_id):
        group_user_ids = await groups_service.group_user_ids(session, group.id)
        group_users = await auth.users_by_ids(session, group_user_ids - set(out))
        for user in group_users.values():
            out.setdefault(user.id, (user, group.name))
    return sorted(out.values(), key=lambda pair: pair[0].name)


# --- ownership + delegated management (spec 87) ---


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
    if team.owner_id is not None and team.owner_id == user_id:
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
    team = await get_team(session, team_id)
    wanted = list(dict.fromkeys(user_ids))
    found = await auth.users_by_ids(session, wanted)
    for user_id in wanted:
        if user_id not in found:
            raise ConflictError(TeamEntity.MANAGER, reason=f"no such user {user_id}")
    await session.execute(delete(TeamManager).where(TeamManager.team_id == team_id))
    for user_id in wanted:
        session.add(TeamManager(team_id=team_id, user_id=user_id))
    await session.flush()
    await _emit_updated(
        session,
        team,
        actor_id,
        {"action": TeamChange.MANAGERS_REPLACED, "user_ids": [str(u) for u in wanted]},
    )
    return wanted


async def transfer_ownership(
    session: AsyncSession, team_id: uuid.UUID, user_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> Team:
    """Reassign `owner_id`. The target must be an active user — handing a team to
    a deactivated account would leave it administrable only by the atom holders.
    The previous owner stays on as a manager, so a transfer never locks anyone out
    by accident (the new owner can revoke)."""
    team = await get_team(session, team_id)
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
    await _emit_updated(
        session,
        team,
        actor_id,
        {"action": TeamChange.OWNER_TRANSFERRED, "owner_id": str(target.id)},
    )
    return team


# --- project attachments ---


async def attach_project_team(
    session: AsyncSession,
    project_id: uuid.UUID,
    data: ProjectTeamAttach,
    actor_id: uuid.UUID | None = None,
) -> ProjectTeam:
    await projects_service.get_project(session, project_id)
    team = await get_team(session, data.team_id)
    if data.role_id is not None:
        role = await auth_roles.get_role(session, data.role_id)
    else:  # compat: role key, defaulting to the builtin member role
        role = await auth_roles.role_by_key(session, data.role or BuiltinRoleKey.MEMBER)
    if await session.get(ProjectTeam, (project_id, data.team_id)):
        raise ConflictError(TeamEntity.PROJECT_TEAM, data.team_id)
    attachment = ProjectTeam(project_id=project_id, team_id=data.team_id, role_id=role.id)
    session.add(attachment)
    await session.flush()
    await _emit_updated(
        session,
        team,
        actor_id,
        {
            "action": TeamChange.PROJECT_ATTACHED,
            "project_id": str(project_id),
            "role_id": str(role.id),
            "role": role.key,
        },
    )
    return attachment


async def update_project_team(
    session: AsyncSession,
    project_id: uuid.UUID,
    team_id: uuid.UUID,
    data: ProjectTeamUpdate,
    actor_id: uuid.UUID | None = None,
) -> ProjectTeam:
    await projects_service.get_project(session, project_id)
    team = await get_team(session, team_id)
    attachment = await session.get(ProjectTeam, (project_id, team_id))
    if attachment is None:
        raise NotFoundError(TeamEntity.PROJECT_TEAM, team_id)
    role = await auth_roles.get_role(session, data.role_id)
    attachment.role_id = role.id
    await session.flush()
    await _emit_updated(
        session,
        team,
        actor_id,
        {
            "action": TeamChange.PROJECT_ROLE_CHANGED,
            "project_id": str(project_id),
            "role_id": str(role.id),
            "role": role.key,
        },
    )
    return attachment


async def detach_project_team(
    session: AsyncSession,
    project_id: uuid.UUID,
    team_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
) -> None:
    await projects_service.get_project(session, project_id)
    team = await get_team(session, team_id)
    result = await session.execute(
        delete(ProjectTeam).where(
            ProjectTeam.project_id == project_id, ProjectTeam.team_id == team_id
        )
    )
    if result.rowcount == 0:
        raise NotFoundError(TeamEntity.PROJECT_TEAM, team_id)
    await _emit_updated(
        session,
        team,
        actor_id,
        {"action": TeamChange.PROJECT_DETACHED, "project_id": str(project_id)},
    )


async def list_project_teams(session: AsyncSession, project_id: uuid.UUID) -> list[ProjectTeam]:
    await projects_service.get_project(session, project_id)
    result = await session.execute(
        select(ProjectTeam).where(ProjectTeam.project_id == project_id)
    )
    return list(result.scalars())


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


async def team_granted_role_ids(
    session: AsyncSession, user_id: uuid.UUID, project_id: uuid.UUID
) -> set[uuid.UUID]:
    """Role ids the user's teams grant on the project (consumed by auth.authz)."""
    result = await session.execute(
        select(ProjectTeam.role_id)
        .join(TeamMember, TeamMember.team_id == ProjectTeam.team_id)
        .where(
            await _membership_filter(session, user_id),
            ProjectTeam.project_id == project_id,
        )
        .distinct()
    )
    return set(result.scalars())


async def team_role_pairs_for_project(
    session: AsyncSession, user_id: uuid.UUID, project_id: uuid.UUID
) -> list[tuple[str, uuid.UUID]]:
    """(team name, role id) pairs the user's teams grant on the project — the
    inspector's provenance variant of `team_granted_role_ids` (RADD-809): same
    rows, keeping WHICH team carried each role."""
    result = await session.execute(
        select(Team.name, ProjectTeam.role_id)
        .join(TeamMember, TeamMember.team_id == ProjectTeam.team_id)
        .join(Team, Team.id == ProjectTeam.team_id)
        .where(
            await _membership_filter(session, user_id),
            ProjectTeam.project_id == project_id,
        )
        .distinct()
    )
    return [(name, role_id) for name, role_id in result.all()]


async def team_granted_role_ids_anywhere(
    session: AsyncSession, user_id: uuid.UUID
) -> set[uuid.UUID]:
    """Every role the user's teams grant on ANY project (the RADD-809 inspector's
    all-scopes subject set)."""
    result = await session.execute(
        select(ProjectTeam.role_id)
        .join(TeamMember, TeamMember.team_id == ProjectTeam.team_id)
        .where(await _membership_filter(session, user_id))
        .distinct()
    )
    return set(result.scalars())


async def team_project_role_rows(
    session: AsyncSession, team_id: uuid.UUID
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """(project id, role id) for every project this team is attached to — what
    membership of the team confers (the RADD-809 team inspector)."""
    result = await session.execute(
        select(ProjectTeam.project_id, ProjectTeam.role_id).where(
            ProjectTeam.team_id == team_id
        )
    )
    return [(project_id, role_id) for project_id, role_id in result.all()]


async def team_granted_role_ids_for_projects(
    session: AsyncSession, user_id: uuid.UUID, project_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, set[uuid.UUID]]:
    """Batched `team_granted_role_ids` for list hydration (one query for N projects)."""
    result = await session.execute(
        select(ProjectTeam.project_id, ProjectTeam.role_id)
        .join(TeamMember, TeamMember.team_id == ProjectTeam.team_id)
        .where(
            await _membership_filter(session, user_id),
            ProjectTeam.project_id.in_(set(project_ids)),
        )
        .distinct()
    )
    granted: dict[uuid.UUID, set[uuid.UUID]] = {}
    for project_id, role_id in result.all():
        granted.setdefault(project_id, set()).add(role_id)
    return granted


async def role_referenced(session: AsyncSession, role_id: uuid.UUID) -> bool:
    """Does any project↔team attachment still grant this role? (role deletion guard)"""
    row = await session.scalar(
        select(ProjectTeam.project_id).where(ProjectTeam.role_id == role_id).limit(1)
    )
    return row is not None


async def _emit_updated(
    session: AsyncSession, team: Team, actor_id: uuid.UUID | None, payload: dict
) -> None:
    await events.emit(
        session,
        event_type=TeamEvent.UPDATED,
        entity_type=TeamEntity.TEAM,
        entity_id=team.id,
        actor_id=actor_id,
        payload=payload,
    )
