from radd.modules.auth.principals import require_key_permission
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from radd.apitypes import TOTAL_COUNT_HEADER
from radd.choices import ChoiceRead
from radd.db import get_session
from radd.exceptions import ForbiddenError
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser

from . import service
from .models import Team
from .schemas import (
    TeamCreate,
    TeamReferenceRead,
    TeamGroupAdd,
    TeamGroupRead,
    TeamGroupChoice,
    TeamManagersUpdate,
    TeamMemberAdd,
    TeamMemberRead,
    TeamPersonChoice,
    TeamStewardshipRead,
    TeamRead,
    TeamTransfer,
    TeamUpdate,
)

team_router = APIRouter(prefix="/teams", tags=["teams"])

Session = Annotated[AsyncSession, Depends(get_session)]


async def _require_manage(session: AsyncSession, user, team: Team, *, writing=True) -> None:
    """Spec 87: administering a team means holding the instance-wide `team.update`
    atom OR being this team's owner/manager. The second half is the delegation —
    a team leader runs their own team without being handed every team."""
    require_key_permission(user, authz.Permission.TEAM_UPDATE if writing else authz.Permission.TEAM_READ)
    if await service.is_team_steward(session, user.id, team):
        return
    await authz.require(session, user, authz.Permission.TEAM_UPDATE)


async def _require_own(session: AsyncSession, user, team: Team, *, writing=True) -> None:
    """Stricter tier: appointing managers and transferring ownership. Managers are
    deliberately excluded — a delegate must not be able to appoint further
    delegates or hand the team away."""
    require_key_permission(user, authz.Permission.TEAM_UPDATE if writing else authz.Permission.TEAM_READ)
    if team.owner_id == user.id:
        return
    await authz.require(session, user, authz.Permission.TEAM_UPDATE)


async def _team_reads(session: AsyncSession, teams: list[Team], user) -> list[TeamRead]:
    # Mutations check global atoms or intrinsic per-team stewardship. Project
    # grants must not advertise global powers, and no project read is required
    # to administer teams through an explicit global grant.
    permissions = await authz.effective_permissions(session, user)
    managers = await service.managers_by_team_ids(session, (team.id for team in teams))
    reads = []
    for team in teams:
        read = TeamRead.model_validate(team)
        read.managers = managers[team.id]
        owns = team.owner_id == user.id
        read.can_manage = owns or user.id in read.managers or authz.holds_base(permissions, authz.Permission.TEAM_UPDATE)
        read.can_delete = owns or authz.holds_base(permissions, authz.Permission.TEAM_DELETE)
        try:
            require_key_permission(user, authz.Permission.TEAM_UPDATE)
        except ForbiddenError:
            read.can_manage = False
        try:
            require_key_permission(user, authz.Permission.TEAM_DELETE)
        except ForbiddenError:
            read.can_delete = False
        reads.append(read)
    return reads


async def _team_read(session: AsyncSession, team: Team, user) -> TeamRead:
    return (await _team_reads(session, [team], user))[0]


@team_router.post("", response_model=TeamRead, status_code=201)
async def create_team(data: TeamCreate, session: Session, user: CurrentUser) -> TeamRead:
    await authz.require(session, user, authz.Permission.TEAM_CREATE)
    team = await service.create_team(session, data, actor_id=user.id)
    return await _team_read(session, team, user)


@team_router.get("/options", response_model=list[ChoiceRead])
async def option_choices(
    response: Response, session: Session, user: CurrentUser,
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    value: Annotated[str | None, Query(max_length=320)] = None,
) -> list[ChoiceRead]:
    rows, total = await service.list_options(session, user, q=q, limit=limit, offset=offset, value=value)
    response.headers[TOTAL_COUNT_HEADER] = str(total)
    return rows


@team_router.get("", response_model=list[TeamRead])
async def list_teams(
    response: Response,
    session: Session,
    user: CurrentUser,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TeamRead]:
    # RADD-816 (F6): the catalog read is a deliverable atom now — Baseline-
    # seeded, so day-one behaviour is the old member floor, but REVOCABLE.
    if not await authz.holds(session, user, authz.Permission.TEAM_READ):
        response.headers[TOTAL_COUNT_HEADER] = "0"
        return []
    if limit is not None:
        response.headers[TOTAL_COUNT_HEADER] = str(await service.count_teams(session, q=q))
    teams = await service.list_teams(session, q=q, limit=limit, offset=offset)
    return await _team_reads(session, teams, user)


@team_router.get("/directory/options", response_model=list[ChoiceRead])
async def team_reference_choices(
    response: Response, session: Session, user: CurrentUser,
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    value: Annotated[str | None, Query(max_length=200)] = None,
) -> list[ChoiceRead]:
    from . import options
    rows, total = await options.reference_options(session, user, q=q, limit=limit, offset=offset, value=value)
    response.headers[TOTAL_COUNT_HEADER] = str(total)
    return rows


@team_router.get("/references", response_model=list[TeamReferenceRead])
async def team_references(
    session: Session, user: CurrentUser,
    ids: Annotated[list[uuid.UUID], Query(max_length=50)] = [],
    include_counts: bool = False,
):
    from . import options
    return await options.references(session, user, ids, include_counts=include_counts)


@team_router.get("/{team_id}", response_model=TeamRead)
async def get_team(team_id: uuid.UUID, session: Session, user: CurrentUser) -> TeamRead:
    await authz.require(session, user, authz.Permission.TEAM_READ)
    return await _team_read(session, await service.get_team(session, team_id), user)


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
    require_key_permission(user, authz.Permission.TEAM_DELETE)
    if team.owner_id != user.id:
        await authz.require(session, user, authz.Permission.TEAM_DELETE)
    await service.delete_team(session, team_id, actor_id=user.id)


@team_router.get("/{team_id}/stewardship", response_model=TeamStewardshipRead)
async def read_stewardship(
    team_id: uuid.UUID, session: Session, user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TeamStewardshipRead:
    team = await service.get_team(session, team_id)
    await _require_own(session, user, team, writing=False)
    return await service.stewardship_page(session, team, limit=limit, offset=offset)


@team_router.get("/{team_id}/steward-candidates", response_model=list[TeamPersonChoice])
async def list_steward_candidates(
    team_id: uuid.UUID, response: Response, session: Session, user: CurrentUser,
    purpose: Literal["manager", "owner"],
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TeamPersonChoice]:
    team = await service.get_team(session, team_id)
    await _require_own(session, user, team, writing=False)
    rows, total = await service.steward_candidates(session, team, purpose=purpose, q=q, limit=limit, offset=offset)
    response.headers[TOTAL_COUNT_HEADER] = str(total)
    return rows


@team_router.post("/{team_id}/managers", status_code=204)
async def add_manager(team_id: uuid.UUID, data: TeamMemberAdd, session: Session, user: CurrentUser) -> None:
    team = await service.get_team(session, team_id, for_update=True)
    await _require_own(session, user, team)
    await service.add_manager(session, team_id, data.user_id, actor_id=user.id)


@team_router.delete("/{team_id}/managers/{user_id}", status_code=204)
async def remove_manager(team_id: uuid.UUID, user_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    team = await service.get_team(session, team_id, for_update=True)
    await _require_own(session, user, team)
    await service.remove_manager(session, team_id, user_id, actor_id=user.id)


@team_router.put("/{team_id}/managers", response_model=TeamRead)
async def replace_managers(
    team_id: uuid.UUID, data: TeamManagersUpdate, session: Session, user: CurrentUser
) -> TeamRead:
    """Replace the team's managers — the people who may administer THIS team
    (spec 87). Owner-gated; a manager cannot appoint further managers."""
    team = await service.get_team(session, team_id, for_update=True)
    await _require_own(session, user, team)
    await service.replace_managers(session, team_id, data.user_ids, actor_id=user.id)
    return await _team_read(session, team, user)


@team_router.post("/{team_id}/transfer", response_model=TeamRead)
async def transfer_team(
    team_id: uuid.UUID, data: TeamTransfer, session: Session, user: CurrentUser
) -> TeamRead:
    """Hand the team to someone else (spec 87). The previous owner stays on as a
    manager so a transfer never locks anyone out."""
    team = await service.get_team(session, team_id, for_update=True)
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


@team_router.get("/{team_id}/member-candidates", response_model=list[TeamPersonChoice])
async def list_member_candidates(
    team_id: uuid.UUID, response: Response, session: Session, user: CurrentUser,
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TeamPersonChoice]:
    team = await service.get_team(session, team_id)
    await _require_manage(session, user, team, writing=False)
    rows, total = await service.candidate_page(session, team_id, q=q, limit=limit, offset=offset)
    response.headers[TOTAL_COUNT_HEADER] = str(total)
    return rows


@team_router.get("/{team_id}/members", response_model=list[TeamMemberRead])
async def list_team_members(
    team_id: uuid.UUID, response: Response, session: Session, user: CurrentUser,
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TeamMemberRead]:
    """Direct and nested group members; deduplicate before search and paging."""
    await authz.require(session, user, authz.Permission.TEAM_READ)
    await service.get_team(session, team_id)
    rows, total = await service.member_page(session, team_id, q=q, limit=limit, offset=offset)
    response.headers[TOTAL_COUNT_HEADER] = str(total)
    return rows


@team_router.get("/{team_id}/groups", response_model=list[TeamGroupRead])
async def list_team_groups(
    team_id: uuid.UUID, response: Response, session: Session, user: CurrentUser,
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TeamGroupRead]:
    await authz.require(session, user, authz.Permission.TEAM_READ)
    await service.get_team(session, team_id)
    rows, total = await service.group_page(session, team_id, q=q, limit=limit, offset=offset)
    response.headers[TOTAL_COUNT_HEADER] = str(total)
    return rows


@team_router.get("/{team_id}/group-candidates", response_model=list[TeamGroupChoice])
async def list_group_candidates(
    team_id: uuid.UUID, response: Response, session: Session, user: CurrentUser,
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[TeamGroupChoice]:
    team = await service.get_team(session, team_id)
    await _require_manage(session, user, team, writing=False)
    rows, total = await service.group_page(session, team_id, candidates=True, q=q, limit=limit, offset=offset)
    response.headers[TOTAL_COUNT_HEADER] = str(total)
    return rows


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


@team_router.get("/{team_id}/access-impact")
async def team_access_impact(team_id: uuid.UUID, session: Session, user: CurrentUser):
    """Stewards need the reach of a membership change without private resource titles."""
    team = await service.get_team(session, team_id)
    await _require_manage(session, user, team, writing=False)
    from radd.modules.auth import grants
    from radd.modules.access import inspect
    from radd.clock import utcnow

    rows = [g for g in await grants.grants_for_subject(session, team_id=team_id)
            if g.expires_at is None or g.expires_at > utcnow()]
    sections = await inspect.subject_access(session, team_ids=[team_id])
    return {
        "roles": len(rows),
        "global_roles": sum(g.project_id is None and g.space_id is None for g in rows),
        "projects": len({g.project_id for g in rows if g.project_id}),
        "spaces": len({g.space_id for g in rows if g.space_id}),
        "resource_rules": [{"label": s.label, "count": sum(r.expires_at is None or r.expires_at > utcnow() for r in s.rows)} for s in sections if s.rows],
    }
