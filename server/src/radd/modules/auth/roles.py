"""Roles as data + direct project membership (spec 06). The auth module owns `roles`.

Builtin roles (admin/member/viewer) are global rows, ensured idempotently on
startup (subscribers.ensure_seeded) and by the seed script. Builtin permission
sets are immutable; deletion requires a role to be custom AND unreferenced
(any role grant) — 409 otherwise.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, NotFoundError
from radd.modules.events import service as events

from .models import Role
from .schemas import RoleCreate, RoleUpdate
from .types import BUILTIN_ROLES, AuthEntity, AuthEvent, BuiltinRoleKey


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
    from . import grants

    # RADD-929: one table to ask. `project_members` and `project_teams` used to
    # need their own reference checks here; both are grants now, so a role in use
    # anywhere is a role some grant names.
    referenced = await grants.role_referenced(session, role_id)
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
