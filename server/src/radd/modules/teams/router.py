import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

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
    TeamManagersUpdate,
    TeamMemberAdd,
    TeamMemberRead,
    TeamRead,
    TeamTransfer,
    TeamUpdate,
)
from .types import MemberSource

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
    if team.owner_id is not None and team.owner_id == user.id:
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
    owns = team.owner_id is not None and team.owner_id == user.id
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
async def list_teams(session: Session, user: CurrentUser) -> list[TeamRead]:
    # Member floor (RADD-788): item.read in SOME project, not the global atom.
    readable = await authz.readable_projects(session, user)
    if not readable:
        return []
    # Team rows carry per-team manage flags; resolve those against the actor's
    # widest project permissions rather than a global union that is now empty for
    # anyone whose access is project-scoped.
    permissions = frozenset().union(*readable.values())
    return [
        await _team_read(session, t, user, permissions)
        for t in await service.list_teams(session)
    ]


@team_router.patch("/{team_id}", response_model=TeamRead)
async def update_team(
    team_id: uuid.UUID, data: TeamUpdate, session: Session, user: CurrentUser
) -> TeamRead:
    """Rename + set/clear the AD group link (spec 84). Renaming is open to the
    team's owner/managers (spec 87); linking to a directory group is not — it
    hands the roster to AD, so it stays with the team.update atom."""
    team = await service.get_team(session, team_id)
    if "directory_group_dn" in data.model_fields_set:
        await authz.require(session, user, authz.Permission.TEAM_UPDATE)
    else:
        await _require_manage(session, user, team)
    updated = await service.update_team(session, team_id, data, actor_id=user.id)
    return await _team_read(session, updated, user)


@team_router.delete("/{team_id}", status_code=204)
async def delete_team(team_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    """Delete a team (spec 87). Owner or a team.delete holder; 409 while the team
    still grants access to any project."""
    team = await service.get_team(session, team_id)
    if not (team.owner_id is not None and team.owner_id == user.id):
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
    await service.get_team(session, team_id)
    await authz.require_member(session, user)
    users = await service.list_team_members(session, team_id)
    sources = {
        row.user_id: MemberSource(row.source)
        for row in await service.team_member_rows(session, team_id)
    }
    return [
        TeamMemberRead(
            user_id=u.id,
            email=u.email,
            name=u.name,
            source=sources.get(u.id, MemberSource.MANUAL),
        )
        for u in users
    ]


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
