"""Roles as data + direct project membership (spec 06). The auth module owns `roles`.

Builtin roles (admin/member/viewer) are global rows, ensured idempotently on
startup (subscribers.ensure_seeded) and by the seed script. Builtin permission
sets are immutable; deletion requires a role to be custom AND unreferenced
(project_members / project_teams) — 409 otherwise.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, NotFoundError
from radd.modules.events import service as events
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project

from .models import ProjectMember, Role
from .schemas import ProjectMemberUpsert, RoleCreate, RoleUpdate
from .service import get_user
from .types import BUILTIN_ROLES, AuthEntity, AuthEvent, BuiltinRoleKey, UserChange


# --- pure guards (unit-tested) ---


def ensure_permissions_mutable(role: Role) -> None:
    """Builtin permission sets are fixed — except Baseline's, which exists to be
    edited (RADD-773).

    Baseline is what every active user holds without being granted anything. It
    was two frozensets in `authz.py` before, which is precisely why nobody could
    see or change it. Making the row editable IS the feature; it stays builtin so
    it cannot be deleted (see `ensure_deletable`) — a missing baseline would
    silently drop every non-admin to no access at all.
    """
    if role.is_builtin and role.key != BuiltinRoleKey.BASELINE.value:
        raise ConflictError(
            AuthEntity.ROLE, reason=f"builtin role '{role.key}' has an immutable permission set"
        )


def ensure_deletable(role: Role, *, referenced: bool) -> None:
    if role.is_builtin:
        raise ConflictError(AuthEntity.ROLE, reason=f"builtin role '{role.key}' cannot be deleted")
    if referenced:
        raise ConflictError(
            AuthEntity.ROLE,
            reason=f"role '{role.key}' is still assigned to members, teams, or instance-wide",
        )


# --- roles ---


async def ensure_builtin_roles(session: AsyncSession) -> None:
    """Idempotently seed the builtin roles (startup ensure + seed both call this)."""
    existing = set(
        (await session.execute(select(Role.key).where(Role.is_builtin))).scalars()
    )
    for spec in BUILTIN_ROLES:
        if spec.key in existing:
            continue
        role = Role(
            key=spec.key,
            name=spec.name,
            description=spec.description,
            permissions=[str(permission) for permission in spec.permissions],
            is_builtin=True,
            position=spec.position,
        )
        session.add(role)
        await session.flush()
        await _emit_role(session, AuthEvent.ROLE_CREATED, role, actor_id=None)


async def list_roles(session: AsyncSession) -> list[Role]:
    result = await session.execute(select(Role).order_by(Role.position, Role.key))
    return list(result.scalars())


async def get_role(session: AsyncSession, role_id: uuid.UUID) -> Role:
    role = await session.get(Role, role_id)
    if role is None:
        raise NotFoundError(AuthEntity.ROLE, role_id)
    return role


async def role_by_key(session: AsyncSession, key: str) -> Role:
    role = await session.scalar(select(Role).where(Role.key == key))
    if role is None:
        raise NotFoundError(AuthEntity.ROLE, key)
    return role


async def roles_by_ids(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, Role]:
    if not ids:
        return {}
    result = await session.execute(select(Role).where(Role.id.in_(ids)))
    return {role.id: role for role in result.scalars()}


async def create_role(
    session: AsyncSession, data: RoleCreate, actor_id: uuid.UUID | None = None
) -> Role:
    existing = await session.scalar(select(Role.id).where(Role.key == data.key))
    if existing:
        raise ConflictError(AuthEntity.ROLE, data.key)
    position = data.position
    if position is None:
        highest = await session.scalar(select(func.max(Role.position)))
        position = (highest or 0) + 1
    role = Role(
        key=data.key,
        name=data.name,
        description=data.description,
        permissions=list(data.permissions),  # spec 93/A2: atoms are validated strings
        is_builtin=False,
        position=position,
    )
    session.add(role)
    await session.flush()
    await _emit_role(session, AuthEvent.ROLE_CREATED, role, actor_id=actor_id)
    return role


async def update_role(
    session: AsyncSession, role_id: uuid.UUID, data: RoleUpdate, actor_id: uuid.UUID | None = None
) -> Role:
    role = await get_role(session, role_id)
    if data.permissions is not None:
        ensure_permissions_mutable(role)
        role.permissions = list(data.permissions)  # spec 93/A2: validated strings
        if role.key == BuiltinRoleKey.BASELINE.value:
            # This request already read the old baseline and memoised it
            # (RADD-773). Drop it, or the admin's own confirming read answers
            # with the value from before their edit.
            from . import authz

            authz.forget_baseline(session)
    if data.name is not None:
        role.name = data.name
    if data.description is not None:
        role.description = data.description
    if data.position is not None:
        role.position = data.position
    await session.flush()
    await _emit_role(session, AuthEvent.ROLE_UPDATED, role, actor_id=actor_id)
    return role


async def delete_role(
    session: AsyncSession, role_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> None:
    role = await get_role(session, role_id)
    # Deferred import: teams loads after auth in the module assembly (same tolerated
    # backward edge as authz -> teams.service).
    from radd.modules.teams import service as teams

    from . import grants

    directly_assigned = await session.scalar(
        select(func.count()).select_from(ProjectMember).where(ProjectMember.role_id == role_id)
    )
    referenced = (
        bool(directly_assigned)
        or await teams.role_referenced(session, role_id)
        or await grants.role_referenced(session, role_id)  # spec 87
    )
    ensure_deletable(role, referenced=referenced)
    await _emit_role(session, AuthEvent.ROLE_DELETED, role, actor_id=actor_id)
    await session.delete(role)
    await session.flush()


async def _emit_role(
    session: AsyncSession, event_type: AuthEvent, role: Role, *, actor_id: uuid.UUID | None
) -> None:
    await events.emit(
        session,
        event_type=event_type,
        entity_type=AuthEntity.ROLE,
        entity_id=role.id,
        actor_id=actor_id,
        payload={"key": role.key, "name": role.name, "permissions": list(role.permissions)},
    )


# --- project members ---


async def list_project_members(
    session: AsyncSession, project_id: uuid.UUID
) -> list[ProjectMember]:
    await projects_service.get_project(session, project_id)
    result = await session.execute(
        select(ProjectMember).where(ProjectMember.project_id == project_id)
    )
    return list(result.scalars())


async def add_project_member(
    session: AsyncSession,
    project_id: uuid.UUID,
    data: ProjectMemberUpsert,
    actor_id: uuid.UUID | None = None,
) -> ProjectMember:
    project = await projects_service.get_project(session, project_id)
    await get_user(session, data.user_id)
    await get_role(session, data.role_id)
    if await session.get(ProjectMember, (project_id, data.user_id)):
        raise ConflictError(AuthEntity.PROJECT_MEMBER, data.user_id)
    member = ProjectMember(project_id=project_id, user_id=data.user_id, role_id=data.role_id)
    session.add(member)
    await session.flush()
    await _emit_member(session, project, member, UserChange.PROJECT_MEMBER_ADDED, actor_id)
    return member


async def update_project_member(
    session: AsyncSession,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    role_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
) -> ProjectMember:
    project = await projects_service.get_project(session, project_id)
    member = await session.get(ProjectMember, (project_id, user_id))
    if member is None:
        raise NotFoundError(AuthEntity.PROJECT_MEMBER, user_id)
    await get_role(session, role_id)
    member.role_id = role_id
    await session.flush()
    await _emit_member(session, project, member, UserChange.PROJECT_MEMBER_ROLE_CHANGED, actor_id)
    return member


async def remove_project_member(
    session: AsyncSession,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
) -> None:
    project = await projects_service.get_project(session, project_id)
    member = await session.get(ProjectMember, (project_id, user_id))
    if member is None:
        raise NotFoundError(AuthEntity.PROJECT_MEMBER, user_id)
    await _emit_member(session, project, member, UserChange.PROJECT_MEMBER_REMOVED, actor_id)
    await session.delete(member)
    await session.flush()


async def _emit_member(
    session: AsyncSession,
    project: Project,
    member: ProjectMember,
    action: UserChange,
    actor_id: uuid.UUID | None,
) -> None:
    await events.emit(
        session,
        event_type=AuthEvent.USER_UPDATED,
        entity_type=AuthEntity.USER,
        entity_id=member.user_id,
        actor_id=actor_id,
        payload={
            "action": action,
            "project_id": str(member.project_id),
            "role_id": str(member.role_id),
        },
    )
