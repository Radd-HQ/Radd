import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, NotFoundError
from radd.modules.auth import roles as auth_roles, service as auth
from radd.modules.auth.models import User
from radd.modules.auth.types import BuiltinRoleKey
from radd.modules.events import service as events
from radd.modules.projects import service as projects_service

from .models import ProjectTeam, Team, TeamManager, TeamMember
from .schemas import ProjectTeamAttach, ProjectTeamUpdate, TeamCreate, TeamUpdate
from .types import MemberSource, TeamChange, TeamEntity, TeamEvent, TeamSource


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


def ensure_membership_editable(team: Team) -> None:
    """Spec 87: a directory team's membership belongs to AD. Refusing here (not
    just in the router) means every path — API, importer, future callers — gets
    the same answer, and the 409 says where to make the change instead."""
    if TeamSource(team.source) is TeamSource.DIRECTORY:
        raise ConflictError(
            TeamEntity.TEAM,
            reason=(
                f"'{team.name}' is linked to the AD group "
                f"'{team.directory_group_name or team.directory_group_dn}' — its membership is "
                "managed in the directory. Change the group there, or unlink the team first."
            ),
        )


async def list_teams(session: AsyncSession) -> list[Team]:
    return list((await session.execute(select(Team).order_by(Team.name))).scalars())


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
    """PATCH /teams/{id} (spec 84): rename + set/clear the AD group link.
    Explicit null in the payload clears the link (model_fields_set semantics)."""
    team = await get_team(session, team_id)
    fields_set = data.model_fields_set
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
    if "directory_group_dn" in fields_set and data.directory_group_dn != team.directory_group_dn:
        team.directory_group_dn = data.directory_group_dn
        team.directory_group_name = data.directory_group_name if data.directory_group_dn else None
        # Spec 87: linking and unlinking are ownership handovers, so the existing
        # rows are re-sourced to match. Linking gives the roster to AD — manual
        # rows become directory rows the next reconcile can prune, otherwise they
        # would be permanently frozen (unremovable by hand, invisible to sync).
        # Unlinking gives it back — directory rows become manual so nobody loses
        # access the moment the link goes, which makes unlink the safe escape hatch.
        if data.directory_group_dn:
            team.source = TeamSource.DIRECTORY
            new_source, payload = MemberSource.DIRECTORY, {
                "action": TeamChange.DIRECTORY_LINKED,
                "directory_group_dn": team.directory_group_dn,
                "directory_group_name": team.directory_group_name,
            }
        else:
            team.source = TeamSource.LOCAL
            new_source, payload = MemberSource.MANUAL, {"action": TeamChange.DIRECTORY_UNLINKED}
        await session.execute(
            update(TeamMember)
            .where(TeamMember.team_id == team.id)
            .values(source=new_source.value)
        )
        await session.flush()
        await _emit_updated(session, team, actor_id, payload)
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
        payload={"name": team.name, "source": team.source},
    )
    await session.delete(team)
    await session.flush()


async def mark_directory_health(
    session: AsyncSession, team: Team, *, missing: bool, actor_id: uuid.UUID | None = None
) -> None:
    """Flag/unflag a linked team whose AD group stopped resolving (spec 87).
    Idempotent — only a CHANGE in health writes and emits, so the hourly loop
    doesn't spam the event log."""
    already = team.directory_missing_since is not None
    if already == missing:
        return
    team.directory_missing_since = datetime.now(UTC).replace(tzinfo=None) if missing else None
    await session.flush()
    await _emit_updated(
        session,
        team,
        actor_id,
        {
            "action": TeamChange.DIRECTORY_MISSING if missing else TeamChange.DIRECTORY_RESTORED,
            "directory_group_dn": team.directory_group_dn,
        },
    )


async def linked_teams(session: AsyncSession) -> list[Team]:
    """Every team with an AD group link — the directory reconcile surface
    (spec 84; consumed by the ldap module)."""
    result = await session.execute(
        select(Team).where(Team.directory_group_dn.is_not(None)).order_by(Team.name)
    )
    return list(result.scalars())


# --- team members ---


async def add_team_member(
    session: AsyncSession, team_id: uuid.UUID, user_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> User:
    team = await get_team(session, team_id)
    ensure_membership_editable(team)  # spec 87: directory teams are read-only here
    user = await auth.get_user(session, user_id)
    if await session.get(TeamMember, (team_id, user_id)):
        raise ConflictError(TeamEntity.MEMBER, user_id)
    session.add(TeamMember(team_id=team_id, user_id=user_id))
    await session.flush()
    await _emit_updated(
        session, team, actor_id, {"action": TeamChange.MEMBER_ADDED, "user_id": str(user_id)}
    )
    return user


async def remove_team_member(
    session: AsyncSession, team_id: uuid.UUID, user_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> None:
    team = await get_team(session, team_id)
    ensure_membership_editable(team)  # spec 87: directory teams are read-only here
    result = await session.execute(
        delete(TeamMember).where(TeamMember.team_id == team_id, TeamMember.user_id == user_id)
    )
    if result.rowcount == 0:
        raise NotFoundError(TeamEntity.MEMBER, user_id)
    await _emit_updated(
        session, team, actor_id, {"action": TeamChange.MEMBER_REMOVED, "user_id": str(user_id)}
    )


async def list_team_members(session: AsyncSession, team_id: uuid.UUID) -> list[User]:
    await get_team(session, team_id)
    member_ids = list(
        (await session.execute(select(TeamMember.user_id).where(TeamMember.team_id == team_id)))
        .scalars()
    )
    users = await auth.users_by_ids(session, member_ids)
    return sorted(users.values(), key=lambda u: u.name)


async def team_member_rows(session: AsyncSession, team_id: uuid.UUID) -> list[TeamMember]:
    """The raw membership rows incl. `source` (spec 84) — feeds the reconcile
    planner and the member-list source badges."""
    await get_team(session, team_id)
    result = await session.execute(select(TeamMember).where(TeamMember.team_id == team_id))
    return list(result.scalars())


async def apply_directory_membership(
    session: AsyncSession,
    team: Team,
    add_user_ids: Iterable[uuid.UUID],
    remove_user_ids: Iterable[uuid.UUID],
    actor_id: uuid.UUID | None = None,
) -> tuple[int, int]:
    """Apply a directory reconcile plan (spec 84): insert DIRECTORY-source rows
    for the joiners, delete DIRECTORY-source rows for the leavers — manual rows
    are never touched. Emits one team.updated (directory_synced) with counts
    when anything changed. Returns (added, removed)."""
    adds = list(dict.fromkeys(add_user_ids))
    removes = list(dict.fromkeys(remove_user_ids))
    for user_id in adds:
        session.add(TeamMember(team_id=team.id, user_id=user_id, source=MemberSource.DIRECTORY))
    removed = 0
    if removes:
        result = await session.execute(
            delete(TeamMember).where(
                TeamMember.team_id == team.id,
                TeamMember.user_id.in_(removes),
                TeamMember.source == MemberSource.DIRECTORY.value,
            )
        )
        removed = result.rowcount or 0
    await session.flush()
    if adds or removed:
        await _emit_updated(
            session,
            team,
            actor_id,
            {"action": TeamChange.DIRECTORY_SYNCED, "added": len(adds), "removed": removed},
        )
    return len(adds), removed


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


async def teams_for_user(session: AsyncSession, user_id: uuid.UUID) -> list[Team]:
    result = await session.execute(
        select(Team)
        .join(TeamMember, TeamMember.team_id == Team.id)
        .where(TeamMember.user_id == user_id)
        .order_by(Team.name)
    )
    return list(result.scalars())


async def user_team_ids(session: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    result = await session.execute(
        select(TeamMember.team_id).where(TeamMember.user_id == user_id)
    )
    return set(result.scalars())


async def team_granted_role_ids(
    session: AsyncSession, user_id: uuid.UUID, project_id: uuid.UUID
) -> set[uuid.UUID]:
    """Role ids the user's teams grant on the project (consumed by auth.authz)."""
    result = await session.execute(
        select(ProjectTeam.role_id)
        .join(TeamMember, TeamMember.team_id == ProjectTeam.team_id)
        .where(TeamMember.user_id == user_id, ProjectTeam.project_id == project_id)
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
        .where(TeamMember.user_id == user_id, ProjectTeam.project_id == project_id)
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
        .where(TeamMember.user_id == user_id)
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
        .where(TeamMember.user_id == user_id, ProjectTeam.project_id.in_(set(project_ids)))
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
