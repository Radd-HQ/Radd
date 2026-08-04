"""Roles CRUD, the permission catalog, and direct project membership (spec 06)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.projects import service as projects_service

from . import authz, grants, roles
from .deps import CurrentUser
from .models import ProjectMember
from radd.exceptions import ConflictError

from .schemas import (
    GlobalGrantRead,
    GlobalGrantsUpdate,
    PermissionRead,
    ProjectMemberRead,
    ProjectMemberRoleUpdate,
    ProjectMemberUpsert,
    RoleCreate,
    RoleGrantCreate,
    RoleRead,
    RoleUpdate,
)
from .types import (
    AuthEntity,
    Permission,
    all_permission_keys,
    permission_description_of,
    permission_parts,
    permission_scope_of,
)

role_router = APIRouter(prefix="/roles", tags=["roles"])
role_grant_router = APIRouter(prefix="/role-grants", tags=["roles"])
permission_router = APIRouter(prefix="/permissions", tags=["roles"])
project_member_router = APIRouter(prefix="/projects", tags=["project members"])

Session = Annotated[AsyncSession, Depends(get_session)]


@role_router.get("", response_model=list[RoleRead])
async def list_roles(session: Session, user: CurrentUser) -> list[RoleRead]:
    # RADD-816 (F6): the catalog read is a deliverable atom now — Baseline-
    # seeded, so day-one behaviour is the old member floor, but REVOCABLE.
    if not await authz.holds(session, user, Permission.ROLE_READ):
        return []
    return [RoleRead.model_validate(r) for r in await roles.list_roles(session)]


@role_router.post("", response_model=RoleRead, status_code=201)
async def create_role(data: RoleCreate, session: Session, user: CurrentUser) -> RoleRead:
    await authz.require(session, user, Permission.ROLE_CREATE)
    return RoleRead.model_validate(await roles.create_role(session, data, actor_id=user.id))


@role_router.patch("/{role_id}", response_model=RoleRead)
async def update_role(
    role_id: uuid.UUID, data: RoleUpdate, session: Session, user: CurrentUser
) -> RoleRead:
    await authz.require(session, user, Permission.ROLE_UPDATE)
    return RoleRead.model_validate(await roles.update_role(session, role_id, data, actor_id=user.id))


@role_router.delete("/{role_id}", status_code=204)
async def delete_role(role_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    await authz.require(session, user, Permission.ROLE_DELETE)
    await roles.delete_role(session, role_id, actor_id=user.id)


_GRANTS_DOC = (
    "Who holds this role INSTANCE-WIDE (spec 87) — the delivery mechanism for global-scope "
    "atoms, which no project attachment can carry. Granted permissions apply at global scope "
    "and on every project. PUT replaces the full set atomically; each entry is exactly one of "
    "user_id/team_id/group_id. Gated on role.update: like editing a role's permission set, handing out "
    "instance-wide grants is escalation-equivalent to instance admin."
)


@role_router.get("/{role_id}/global-grants", response_model=list[GlobalGrantRead])
async def list_global_grants(
    role_id: uuid.UUID, session: Session, user: CurrentUser
) -> list[GlobalGrantRead]:
    await roles.get_role(session, role_id)
    await authz.require(session, user, Permission.ROLE_READ)
    return [GlobalGrantRead.model_validate(g) for g in await grants.list_grants(session, role_id)]


@role_router.put(
    "/{role_id}/global-grants", response_model=list[GlobalGrantRead], description=_GRANTS_DOC
)
async def replace_global_grants(
    role_id: uuid.UUID, data: GlobalGrantsUpdate, session: Session, user: CurrentUser
) -> list[GlobalGrantRead]:
    await authz.require(session, user, Permission.ROLE_UPDATE)
    rows = await grants.replace_grants(session, role_id, data.grants, actor_id=user.id)
    return [GlobalGrantRead.model_validate(g) for g in rows]


_GRANT_DIALOG_DOC = (
    "The unified Grant Role dialog (spec 91 → RADD-791 → RADD-832): grant a role to a "
    "user, team, or directory group "
    "at global scope (no ids), on specific projects, or in specific wiki spaces. One "
    "dialog for every scope — a second one for spaces is how two scopes become two sets "
    "of rules. Like editing a role, handing out grants is escalation-equivalent — gated "
    "on role.update."
)


@role_grant_router.get("", response_model=list[GlobalGrantRead])
async def list_role_grants(
    session: Session,
    user: CurrentUser,
    team_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    group_id: uuid.UUID | None = None,
    space_id: uuid.UUID | None = None,
) -> list[GlobalGrantRead]:
    """Role grants, by SUBJECT (the team/user/group Roles tab) or by SPACE
    (RADD-793).

    Exactly one of team_id/user_id/group_id/space_id. The space direction is
    the one an admin actually asks — "who has access to this space?" — and
    asking it by walking every user was not an answer.
    """
    await authz.require_member(session, user)
    named = [x for x in (team_id, user_id, group_id, space_id) if x is not None]
    if len(named) != 1:
        raise ConflictError(
            AuthEntity.GLOBAL_GRANT,
            reason="exactly one of team_id/user_id/group_id/space_id",
        )
    if space_id is not None:
        rows = await grants.grants_for_space(session, space_id)
    else:
        rows = await grants.grants_for_subject(
            session, user_id=user_id, team_id=team_id, group_id=group_id
        )
    return [GlobalGrantRead.model_validate(g) for g in rows]


@role_grant_router.post(
    "", response_model=list[GlobalGrantRead], status_code=201, description=_GRANT_DIALOG_DOC
)
async def create_role_grant(
    data: RoleGrantCreate, session: Session, user: CurrentUser
) -> list[GlobalGrantRead]:
    await authz.require(session, user, Permission.ROLE_UPDATE)
    # (project_id, space_id) pairs — at most one of each is ever set. No ids at
    # all means one instance-wide grant, which is the spec-87 behaviour.
    scopes: list[tuple[uuid.UUID | None, uuid.UUID | None]] = [
        *((project_id, None) for project_id in data.project_ids),
        *((None, space_id) for space_id in data.space_ids),
    ] or [(None, None)]
    rows = [
        await grants.create_grant(
            session,
            data.role_id,
            user_id=data.user_id,
            team_id=data.team_id,
            group_id=data.group_id,
            project_id=project_id,
            space_id=space_id,
            actor_id=user.id,
        )
        for project_id, space_id in scopes
    ]
    return [GlobalGrantRead.model_validate(g) for g in rows]


@role_grant_router.delete("/{grant_id}", status_code=204)
async def delete_role_grant(grant_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    await authz.require(session, user, Permission.ROLE_UPDATE)
    await grants.delete_grant(session, grant_id, actor_id=user.id)


@permission_router.get("", response_model=list[PermissionRead])
async def permission_catalog(session: Session, user: CurrentUser) -> list[PermissionRead]:
    """Every permission the system knows, with scope — for the admin role-matrix UI.
    VOCABULARY, not data (atom names and descriptions carry no instance state),
    so it stays on the member floor rather than role.read (RADD-816)."""
    await authz.require_member(session, user)
    # Builtins first, in enum order (parity), then any plugin-registered atoms
    # (spec 93/A2 — a plugin's atoms appear in the matrix with no edit to auth).
    builtin = [p.value for p in Permission]
    builtin_set = set(builtin)
    extra = sorted(k for k in all_permission_keys() if k not in builtin_set)
    catalog = []
    for key in [*builtin, *extra]:
        resource, action = permission_parts(key)
        catalog.append(
            PermissionRead(
                key=key,
                description=permission_description_of(key),
                scope=permission_scope_of(key),
                resource=resource,
                action=action,
            )
        )
    return catalog


# --- direct project membership ---


async def _member_read(session: Session, member: ProjectMember) -> ProjectMemberRead:
    role = await roles.get_role(session, member.role_id)
    return ProjectMemberRead(
        project_id=member.project_id,
        user_id=member.user_id,
        role_id=member.role_id,
        role=role.key,
    )


@project_member_router.get("/{project_id}/members", response_model=list[ProjectMemberRead])
async def list_project_members(
    project_id: uuid.UUID, session: Session, user: CurrentUser
) -> list[ProjectMemberRead]:
    project = await projects_service.get_project(session, project_id)
    await authz.require(session, user, Permission.PROJECT_MANAGE, project=project)
    members = await roles.list_project_members(session, project_id)
    keys = await roles.roles_by_ids(session, {m.role_id for m in members})
    return [
        ProjectMemberRead(
            project_id=m.project_id,
            user_id=m.user_id,
            role_id=m.role_id,
            role=keys[m.role_id].key,
        )
        for m in members
    ]


@project_member_router.post(
    "/{project_id}/members", response_model=ProjectMemberRead, status_code=201
)
async def add_project_member(
    project_id: uuid.UUID, data: ProjectMemberUpsert, session: Session, user: CurrentUser
) -> ProjectMemberRead:
    project = await projects_service.get_project(session, project_id)
    await authz.require(session, user, Permission.MEMBER_CREATE, project=project)
    member = await roles.add_project_member(session, project_id, data, actor_id=user.id)
    return await _member_read(session, member)


@project_member_router.patch(
    "/{project_id}/members/{user_id}", response_model=ProjectMemberRead
)
async def update_project_member(
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    data: ProjectMemberRoleUpdate,
    session: Session,
    user: CurrentUser,
) -> ProjectMemberRead:
    project = await projects_service.get_project(session, project_id)
    await authz.require(session, user, Permission.MEMBER_UPDATE, project=project)
    member = await roles.update_project_member(
        session, project_id, user_id, data.role_id, actor_id=user.id
    )
    return await _member_read(session, member)


@project_member_router.delete("/{project_id}/members/{user_id}", status_code=204)
async def remove_project_member(
    project_id: uuid.UUID, user_id: uuid.UUID, session: Session, user: CurrentUser
) -> None:
    project = await projects_service.get_project(session, project_id)
    await authz.require(session, user, Permission.MEMBER_DELETE, project=project)
    await roles.remove_project_member(session, project_id, user_id, actor_id=user.id)
