import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from radd.apitypes import TOTAL_COUNT_HEADER
from radd.db import get_session
from radd.modules.auth import authz, roles as auth_roles
from radd.modules.auth.deps import CurrentUser
from radd.modules.projects import service as projects_service

from . import service
from .models import ProjectTeam, Team
from .schemas import (
    ProjectTeamAttach,
    ProjectTeamRead,
    ProjectTeamUpdate,
    TeamCreate,
    TeamGroupAdd,
    TeamGroupRead,
    TeamManagersUpdate,
    TeamMemberAdd,
    TeamMemberRead,
    TeamRead,
    TeamTransfer,
    TeamUpdate,
)

team_router = APIRouter(prefix="/teams", tags=["teams"])
project_team_router = APIRouter(prefix="/projects", tags=["teams"])

Session = Annotated[AsyncSession, Depends(get_session)]


async def _require_manage(session: AsyncSession, user, team: Team) -> None:
    """Spec 87: administering a team means holding the instance-wide `team.update`
    atom OR being this team's owner/manager. The second half is the delegation —
    a team leader runs their own team without being handed every team."""
    if await service.is_team_steward(session, user.id, team):
        return
    await authz.require(session, user, authz.Permission.TEAM_UPDATE)


async def _require_own(session: AsyncSession, user, team: Team) -> None:
    """Stricter tier: appointing managers and transferring ownership. Managers are
    deliberately excluded — a delegate must not be able to appoint further
    delegates or hand the team away."""
    if team.owner_id == user.id:
        return
    await authz.require(session, user, authz.Permission.TEAM_UPDATE)


async def _team_read(
    session: AsyncSession,
    team: Team,
    user,
    global_permissions: frozenset[authz.Permission] | None = None,
) -> TeamRead:
    """Hydrate a team with its managers + this actor's capabilities (spec 87).

    `global_permissions` is passed in by the list endpoint: the atom half of the
    answer is the same for every row, so resolving it once keeps listing N teams
    from costing N permission unions.
    """
    if global_permissions is None:
        global_permissions = await authz.effective_permissions(session, user)
    read = TeamRead.model_validate(team)
    read.managers = await service.list_managers(session, team.id)
    owns = team.owner_id == user.id
    steward = owns or await service.is_team_steward(session, user.id, team)
    read.can_manage = steward or authz.Permission.TEAM_UPDATE in global_permissions
    read.can_delete = owns or authz.Permission.TEAM_DELETE in global_permissions
    return read


@team_router.post("", response_model=TeamRead, status_code=201)
async def create_team(data: TeamCreate, session: Session, user: CurrentUser) -> TeamRead:
    await authz.require(session, user, authz.Permission.TEAM_CREATE)
    team = await service.create_team(session, data, actor_id=user.id)
    return await _team_read(session, team, user)


@team_router.get("", response_model=list[TeamRead])
async def list_teams(
    response: Response,
    session: Session,
    user: CurrentUser,
    q: str | None = None,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TeamRead]:
    # RADD-816 (F6): the catalog read is a deliverable atom now — Baseline-
    # seeded, so day-one behaviour is the old member floor, but REVOCABLE.
    if not await authz.holds(session, user, authz.Permission.TEAM_READ):
        return []
    readable = await authz.readable_projects(session, user)
    # Team rows carry per-team manage flags; resolve those against the actor's
    # widest project permissions rather than a global union that is now empty for
    # anyone whose access is project-scoped.
    permissions = frozenset().union(*readable.values())
    if limit is not None:
        response.headers[TOTAL_COUNT_HEADER] = str(await service.count_teams(session, q=q))
    return [
        await _team_read(session, t, user, permissions)
        for t in await service.list_teams(session, q=q, limit=limit, offset=offset)
    ]


@team_router.patch("/{team_id}", response_model=TeamRead)
async def update_team(
    team_id: uuid.UUID, data: TeamUpdate, session: Session, user: CurrentUser
) -> TeamRead:
    """Rename — open to the team's owner/managers (spec 87). (RADD-829 retired
    the AD-link branch; group membership rides /teams/{id}/groups.)"""
    team = await service.get_team(session, team_id)
    await _require_manage(session, user, team)
    updated = await service.update_team(session, team_id, data, actor_id=user.id)
    return await _team_read(session, updated, user)


@team_router.delete("/{team_id}", status_code=204)
async def delete_team(team_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    """Delete a team (spec 87). Owner or a team.delete holder; 409 while the team
    still grants access to any project."""
    team = await service.get_team(session, team_id)
    if team.owner_id != user.id:
        await authz.require(session, user, authz.Permission.TEAM_DELETE)
    await service.delete_team(session, team_id, actor_id=user.id)


@team_router.put("/{team_id}/managers", response_model=TeamRead)
async def replace_managers(
    team_id: uuid.UUID, data: TeamManagersUpdate, session: Session, user: CurrentUser
) -> TeamRead:
    """Replace the team's managers — the people who may administer THIS team
    (spec 87). Owner-gated; a manager cannot appoint further managers."""
    team = await service.get_team(session, team_id)
    await _require_own(session, user, team)
    await service.replace_managers(session, team_id, data.user_ids, actor_id=user.id)
    return await _team_read(session, team, user)


@team_router.post("/{team_id}/transfer", response_model=TeamRead)
async def transfer_team(
    team_id: uuid.UUID, data: TeamTransfer, session: Session, user: CurrentUser
) -> TeamRead:
    """Hand the team to someone else (spec 87). The previous owner stays on as a
    manager so a transfer never locks anyone out."""
    team = await service.get_team(session, team_id)
    await _require_own(session, user, team)
    updated = await service.transfer_ownership(session, team_id, data.user_id, actor_id=user.id)
    return await _team_read(session, updated, user)


@team_router.post("/{team_id}/members", response_model=TeamMemberRead, status_code=201)
async def add_team_member(
    team_id: uuid.UUID, data: TeamMemberAdd, session: Session, user: CurrentUser
) -> TeamMemberRead:
    team = await service.get_team(session, team_id)
    await _require_manage(session, user, team)
    member = await service.add_team_member(session, team_id, data.user_id, actor_id=user.id)
    return TeamMemberRead(user_id=member.id, email=member.email, name=member.name)


@team_router.delete("/{team_id}/members/{user_id}", status_code=204)
async def remove_team_member(
    team_id: uuid.UUID, user_id: uuid.UUID, session: Session, user: CurrentUser
) -> None:
    team = await service.get_team(session, team_id)
    await _require_manage(session, user, team)
    await service.remove_team_member(session, team_id, user_id, actor_id=user.id)


@team_router.get("/{team_id}/members", response_model=list[TeamMemberRead])
async def list_team_members(
    team_id: uuid.UUID, session: Session, user: CurrentUser
) -> list[TeamMemberRead]:
    """Every PERSON on the team (RADD-829): direct rows plus the people its
    member groups resolve to, nesting included — `via_group` names the carrier."""
    await authz.require(session, user, authz.Permission.TEAM_READ)
    return [
        TeamMemberRead(user_id=u.id, email=u.email, name=u.name, via_group=via)
        for u, via in await service.member_users_with_via(session, team_id)
    ]


@team_router.get("/{team_id}/groups", response_model=list[TeamGroupRead])
async def list_team_groups(
    team_id: uuid.UUID, session: Session, user: CurrentUser
) -> list[TeamGroupRead]:
    await authz.require(session, user, authz.Permission.TEAM_READ)
    return [
        TeamGroupRead(
            group_id=g.id,
            name=g.name,
            dn=g.dn,
            directory_missing_since=g.directory_missing_since,
        )
        for g in await service.team_groups(session, team_id)
    ]


@team_router.post("/{team_id}/groups", response_model=TeamGroupRead, status_code=201)
async def add_team_group(
    team_id: uuid.UUID, data: TeamGroupAdd, session: Session, user: CurrentUser
) -> TeamGroupRead:
    team = await service.get_team(session, team_id)
    await _require_manage(session, user, team)
    group = await service.add_team_group(session, team_id, data.group_id, actor_id=user.id)
    return TeamGroupRead(
        group_id=group.id,
        name=group.name,
        dn=group.dn,
        directory_missing_since=group.directory_missing_since,
    )


@team_router.delete("/{team_id}/groups/{group_id}", status_code=204)
async def remove_team_group(
    team_id: uuid.UUID, group_id: uuid.UUID, session: Session, user: CurrentUser
) -> None:
    team = await service.get_team(session, team_id)
    await _require_manage(session, user, team)
    await service.remove_team_group(session, team_id, group_id, actor_id=user.id)


@team_router.get("/{team_id}/access")
async def team_access(team_id: uuid.UUID, session: Session, user: CurrentUser) -> dict:
    """What membership of this team confers (RADD-809): atoms via project
    attachments and role grants, plus the resource grants naming the team.
    Gated like the user inspector — it describes conferred authority."""
    from radd.modules.access import inspect as access_inspect
    from radd.modules.auth.schemas import PermissionSourceRead, ResourceTypeAccessRead

    team = await service.get_team(session, team_id)
    await authz.require(session, user, authz.Permission.USER_MANAGE)
    atoms = await authz.team_permission_sources(session, team.id)
    resources = await access_inspect.subject_access(
        session, team_ids={team.id}, team_names={team.id: team.name}
    )
    return {
        "atoms": [
            PermissionSourceRead.model_validate(a, from_attributes=True).model_dump(mode="json")
            for a in atoms
        ],
        "resources": [
            ResourceTypeAccessRead.model_validate(s, from_attributes=True).model_dump(mode="json")
            for s in resources
        ],
    }


async def _attachment_reads(
    session: AsyncSession, attachments: list[ProjectTeam]
) -> list[ProjectTeamRead]:
    """Hydrate the granted role's key onto each attachment (one batched lookup)."""
    roles = await auth_roles.roles_by_ids(session, {a.role_id for a in attachments})
    return [
        ProjectTeamRead(
            project_id=a.project_id,
            team_id=a.team_id,
            role_id=a.role_id,
            role=roles[a.role_id].key,
        )
        for a in attachments
    ]


@project_team_router.post(
    "/{project_id}/teams", response_model=ProjectTeamRead, status_code=201
)
async def attach_project_team(
    project_id: uuid.UUID, data: ProjectTeamAttach, session: Session, user: CurrentUser
) -> ProjectTeamRead:
    project = await projects_service.get_project(session, project_id)
    await authz.require(session, user, authz.Permission.MEMBER_CREATE, project=project)
    # RADD-826 (D14): a delegate cannot attach a role carrying atoms they do
    # not hold at THIS project's scope.
    if not await authz.holds(session, user, authz.Permission.ROLE_UPDATE):
        from radd.modules.auth import roles as auth_roles
        from radd.modules.auth.roles_router import ensure_delegated_role_coverage

        await ensure_delegated_role_coverage(
            session, user, await auth_roles.get_role(session, data.role_id), project
        )
    attachment = await service.attach_project_team(session, project_id, data, actor_id=user.id)
    return (await _attachment_reads(session, [attachment]))[0]


@project_team_router.get("/{project_id}/teams", response_model=list[ProjectTeamRead])
async def list_project_teams(
    project_id: uuid.UUID, session: Session, user: CurrentUser
) -> list[ProjectTeamRead]:
    project = await projects_service.get_project(session, project_id)
    await authz.require(session, user, authz.Permission.ITEM_READ, project=project)
    attachments = await service.list_project_teams(session, project_id)
    return await _attachment_reads(session, attachments)


@project_team_router.patch("/{project_id}/teams/{team_id}", response_model=ProjectTeamRead)
async def update_project_team(
    project_id: uuid.UUID,
    team_id: uuid.UUID,
    data: ProjectTeamUpdate,
    session: Session,
    user: CurrentUser,
) -> ProjectTeamRead:
    project = await projects_service.get_project(session, project_id)
    await authz.require(session, user, authz.Permission.MEMBER_UPDATE, project=project)
    attachment = await service.update_project_team(
        session, project_id, team_id, data, actor_id=user.id
    )
    return (await _attachment_reads(session, [attachment]))[0]


@project_team_router.delete("/{project_id}/teams/{team_id}", status_code=204)
async def detach_project_team(
    project_id: uuid.UUID, team_id: uuid.UUID, session: Session, user: CurrentUser
) -> None:
    project = await projects_service.get_project(session, project_id)
    await authz.require(session, user, authz.Permission.MEMBER_DELETE, project=project)
    await service.detach_project_team(session, project_id, team_id, actor_id=user.id)
