"""The pure decision core and THE seam (`effective_permissions`/`require`/
`holds_base`). Re-exported by `authz.py`; tests monkeypatch THIS module."""

import uuid
from collections.abc import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ForbiddenError
from radd.modules.projects.models import Project

from . import grants
from .models import Role, User
from .principals import is_instance_admin
from .types import (
    BuiltinRoleKey,
    InstanceRole,
    Permission,
    all_permission_keys,
    expand_permissions,
)

# The floor is the Baseline ROLE (RADD-773), passed into the combiners so they
# stay pure. With no Baseline row (mid-migration, unit tests) the floor is
# EMPTY: a missing baseline must fail closed, never reinstate a default.
EMPTY_BASELINE: frozenset[Permission] = frozenset()


# --- pure decision core (unit-tested) ---


def combine_permissions(
    *,
    instance_role: str,
    permission_sets: Iterable[Iterable[str]],
    baseline: Iterable[str] = EMPTY_BASELINE,
) -> frozenset[Permission]:
    """Union of the granted role sets plus `baseline` (the floor); admins get all.
    Atoms stay strings: a role may grant a plugin atom that is no `Permission` member."""
    if InstanceRole(instance_role) is InstanceRole.ADMIN:
        return all_permission_keys()
    granted = {str(value) for permissions in permission_sets for value in permissions}
    granted |= {str(p) for p in baseline}
    return expand_permissions(granted)


def global_scope_permissions(
    instance_role: str | None,
    permission_sets: Iterable[Iterable[str]] = (),
    baseline: Iterable[str] = EMPTY_BASELINE,
) -> frozenset[Permission]:
    """Global scope (specs 86/87): admin -> all; inactive (None) -> nothing; any
    other active user -> the floor + roles granted instance-wide. The same floor
    feeds `combine_permissions` (RADD-773)."""
    if instance_role is None:
        return frozenset()
    if InstanceRole(instance_role) is InstanceRole.ADMIN:
        return all_permission_keys()
    granted = {str(value) for permissions in permission_sets for value in permissions}
    # Expand umbrellas (spec 50): a user holding cycle.manage at global scope
    # gets cycle.create/update/delete so the granular endpoint checks resolve.
    return expand_permissions(granted | {str(p) for p in baseline})


def _active_role(user: User) -> str | None:
    """Inactive -> None (no access anywhere); else the user's instance role."""
    if not user.active:
        return None
    return user.instance_role


async def is_admin(session: AsyncSession, user: User) -> bool:
    """An active instance admin whose credential permits the administrative bypass."""
    del session  # kept in the signature: every caller already threads one
    return is_instance_admin(user)


async def _permission_sets_for_roles(
    session: AsyncSession, role_ids: set[uuid.UUID]
) -> list[Sequence[str]]:
    if not role_ids:
        return []
    result = await session.execute(select(Role.permissions).where(Role.id.in_(role_ids)))
    return list(result.scalars())


async def _project_permission_sets(
    session: AsyncSession, user_id: uuid.UUID, project: Project
) -> list[Sequence[str]]:
    """The permission sets of every role granted to the user on the project."""
    return await _permission_sets_for_roles(
        session, await grants.granted_role_ids(session, user_id, project.id)
    )


async def _global_permission_sets(
    session: AsyncSession, user_id: uuid.UUID
) -> list[Sequence[str]]:
    """The permission sets of every role granted to the user instance-wide (spec 87)."""
    return await _permission_sets_for_roles(session, await grants.granted_role_ids(session, user_id))


#: Key under which the request's baseline lookup is memoised on the session.
_BASELINE_CACHE_KEY = "radd.baseline_permissions"

_REQUESTER_CACHE_KEY = "radd.requester_floor"


async def floor_permissions(session: AsyncSession, user: User) -> frozenset[Permission]:
    """The user's FLOOR (RADD-828): the Baseline for staff-shaped accounts, the
    Requester role for email-provisioned ones — the Baseline is the operator's
    STAFF policy row, never a stranger's. Same memoisation, same fail-closed default."""
    from .types import UserSource

    source = getattr(user, "source", None)
    if source == UserSource.PRINCIPAL.value:
        # Spec 121: the principals hold NOTHING by default — the world's access
        # is exactly the grants written against the principal rows.
        return frozenset()
    if source != UserSource.EMAIL.value:
        return await baseline_permissions(session)
    cached: frozenset[Permission] | None = session.info.get(_REQUESTER_CACHE_KEY)
    if cached is not None:
        return cached
    row = (
        await session.execute(
            select(Role.permissions).where(Role.key == BuiltinRoleKey.REQUESTER.value)
        )
    ).scalar()
    resolved = frozenset(row or ())
    session.info[_REQUESTER_CACHE_KEY] = resolved
    return resolved


async def baseline_permissions(session: AsyncSession) -> frozenset[Permission]:
    """The Baseline role's atoms (RADD-773), memoised on `session.info` for the
    request. A missing row answers EMPTY — fail closed."""
    cached: frozenset[Permission] | None = session.info.get(_BASELINE_CACHE_KEY)
    if cached is not None:
        return cached
    row = (
        await session.execute(
            select(Role.permissions).where(Role.key == BuiltinRoleKey.BASELINE.value)
        )
    ).scalar_one_or_none()
    resolved = frozenset(row) if row else EMPTY_BASELINE
    session.info[_BASELINE_CACHE_KEY] = resolved
    return resolved


def forget_baseline(session: AsyncSession) -> None:
    """Drop the memo after editing the Baseline role, or the editing request goes
    on answering with the value it read before the write."""
    session.info.pop(_BASELINE_CACHE_KEY, None)


# --- the seam ---


async def effective_permissions(
    session: AsyncSession,
    user: User,
    *,
    project: Project | None = None,
    space_id: uuid.UUID | None = None,
) -> frozenset[Permission]:
    """The union the user holds in a project, a wiki SPACE (RADD-791) or globally
    (neither); empty for inactive users. Narrowed by the API key's scope (spec 113)."""
    if project is not None and space_id is not None:
        raise ValueError("resolve against a project or a space, not both")
    role = _active_role(user)
    if role is None:
        return frozenset()
    if InstanceRole(role) is InstanceRole.ADMIN:
        resolved = all_permission_keys()
    elif space_id is not None:
        permission_sets = await _permission_sets_for_roles(
            session, await grants.granted_role_ids(session, user.id, space_id=space_id)
        )
        resolved = combine_permissions(
            instance_role=user.instance_role,
            permission_sets=permission_sets,
            baseline=await floor_permissions(session, user),
        )
    elif project is not None:
        permission_sets = await _project_permission_sets(session, user.id, project)
        resolved = combine_permissions(
            instance_role=user.instance_role,
            permission_sets=permission_sets,
            baseline=await floor_permissions(session, user),
        )
    else:
        resolved = global_scope_permissions(
            role,
            await _global_permission_sets(session, user.id),
            baseline=await floor_permissions(session, user),
        )
    return _narrow_to_key_scope(user, resolved, project.id if project is not None else None)


def _narrow_to_key_scope(
    user: User, permissions: frozenset[Permission], project_id: uuid.UUID | None
) -> frozenset[Permission]:
    """Spec 113: intersect with the scope of the API key that authenticated this
    request, if any. Applied to EVERY resolution — including the admin shortcut,
    because a scoped key held by an admin is the whole point. Unscoped principals
    (session cookies, personal tokens, internal actors) are returned untouched."""
    scope = getattr(user, "token_scope", None)
    if scope is None:
        return permissions
    return scope.narrow(permissions, project_id)


def holds_base(
    permissions: "frozenset[Permission] | frozenset[str]", permission: "Permission | str"
) -> bool:
    """Does the set hold `permission` in ANY form — unqualified or relation-
    qualified (RADD-823)? Which qualifier is a second question (`relations_held`)."""
    if permission in permissions:
        return True
    prefix = f"{permission}@"
    return any(str(atom).startswith(prefix) for atom in permissions)


async def require(
    session: AsyncSession,
    user: User,
    permission: Permission,
    *,
    project: Project | None = None,
    space_id: uuid.UUID | None = None,
) -> frozenset[Permission]:
    """Raise ForbiddenError (-> 403) unless the user holds `permission` in the scope.

    Returns the full effective-permission union so callers can reuse it (field-level
    visibility, response shaping) without a second lookup.
    """
    permissions = await effective_permissions(
        session, user, project=project, space_id=space_id
    )
    # RADD-823: a relation-qualified form HOLDS the base — the row-level
    # narrowing is enforced by the surfaces that see rows (the relation
    # resolvers), never by pretending the atom is absent.
    if not holds_base(permissions, permission):
        if project is not None:
            raise ForbiddenError(f"permission '{permission}' denied on project {project.key}")
        if space_id is not None:
            raise ForbiddenError(f"permission '{permission}' denied in this space")
        raise ForbiddenError(f"permission '{permission}' denied")
    return permissions
