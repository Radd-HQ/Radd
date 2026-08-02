"""Action RBAC — the single enforcement seam (spec 03, reworked by specs 06/86).

Roles are data (`roles` table: builtin admin/member/viewer + custom rows).
A user's effective permissions on a project are the UNION of:

- the role their direct `project_members` row grants,
- the roles their teams' `project_teams` attachments grant,
- the roles granted to them instance-wide (`global_role_grants`, spec 87),
- the member floor — the builtin `viewer` set — held by EVERY ACTIVE user
  (spec 86: being an active user of the server IS membership).

Admins hold every permission. "Admin" means `users.instance_role == admin` —
THE one admin predicate (spec 86 stage 3 dropped the membership compat tier).
GLOBAL-scope checks (no project): admin -> all, active user -> the member
global set PLUS whatever their instance-wide role grants add, inactive ->
nothing. Spec 87 added that last term: before it, a global-scope check read
`instance_role` alone, so every global atom the roles matrix offered
(label.create, team.update, sla.*, …) was ungrantable to a non-admin.

The decision core is pure (`combine_permissions`, `global_scope_permissions`); the
DB lookups are thin and monkeypatched in `tests/test_authz.py`.
"""

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ForbiddenError
from radd.modules.projects.models import Project

from . import grants
from .models import ProjectMember, Role, User
from .types import (
    BuiltinRoleKey,
    InstanceRole,
    Permission,  # noqa: F401  — re-exported: every module imports Permission from here
    all_permission_keys,
    builtin_role,
    expand_permissions,
)

# Builtin atom set — kept for back-compat imports. The admin's *effective* set is
# `all_permission_keys()` (builtin ∪ plugin-registered, spec 93/A2), which equals
# this in the default config and grows as plugins register atoms.
ALL_PERMISSIONS: frozenset[Permission] = frozenset(Permission)

# Open-visibility floor: what being an active user grants on every project.
# Builtin permission sets are immutable (PATCH -> 409), so the seeded viewer
# definition IS the builtin viewer row — no per-scope query needed.
MEMBER_FLOOR: frozenset[Permission] = frozenset(builtin_role(BuiltinRoleKey.VIEWER).permissions)

# What an active user holds at GLOBAL scope (spec 36 widening): the floor plus
# running cycles, seeing team timesheets, and writing docs (spec 43 — a
# read-only-for-members wiki is useless). automation/sla manage stay
# admin-only — rules execute as the SYSTEM actor, so authoring them is
# privilege-bearing.
MEMBER_GLOBAL_SCOPE: frozenset[Permission] = MEMBER_FLOOR | frozenset(
    {Permission.CYCLE_MANAGE, Permission.TIMESHEET_VIEW, Permission.DOC_WRITE}
)


# --- pure decision core (unit-tested) ---


def combine_permissions(
    *,
    instance_role: str,
    permission_sets: Iterable[Iterable[str]],
) -> frozenset[Permission]:
    """Union of the granted role permission sets, plus the member floor. Admins get all.

    Atoms flow as strings (spec 93/A2): a role may grant a plugin-contributed atom
    that isn't a builtin `Permission` enum member, so we no longer coerce to the enum."""
    if InstanceRole(instance_role) is InstanceRole.ADMIN:
        return all_permission_keys()
    granted = {str(value) for permissions in permission_sets for value in permissions}
    granted |= {str(p) for p in MEMBER_FLOOR}
    return expand_permissions(granted)


def global_scope_permissions(
    instance_role: str | None,
    permission_sets: Iterable[Iterable[str]] = (),
) -> frozenset[Permission]:
    """Global-scope checks (spec 86): admin -> all, member (any active user) ->
    the member set, None (inactive) -> none.

    `permission_sets` (spec 87) are the sets of the roles granted to the user
    instance-wide — the only way a non-admin holds a global atom.
    """
    if instance_role is None:
        return frozenset()
    if InstanceRole(instance_role) is InstanceRole.ADMIN:
        return all_permission_keys()
    granted = {str(value) for permissions in permission_sets for value in permissions}
    # Expand umbrellas (spec 50): a member holding cycle.manage at global scope
    # gets cycle.create/update/delete so the granular endpoint checks resolve.
    return expand_permissions(granted | {str(p) for p in MEMBER_GLOBAL_SCOPE})


def _active_role(user: User) -> str | None:
    """Inactive -> None (no access anywhere); else the user's instance role."""
    if not user.active:
        return None
    return user.instance_role


async def is_admin(session: AsyncSession, user: User) -> bool:
    """Active AND instance_role == admin — THE admin predicate (spec 86 stage 3)."""
    del session  # kept in the signature: every caller already threads one
    return user.active and InstanceRole(user.instance_role) is InstanceRole.ADMIN


async def _granted_role_ids(
    session: AsyncSession, user_id: uuid.UUID, project: Project
) -> set[uuid.UUID]:
    """Role ids the user holds on the project: direct membership + team
    attachments + instance-wide grants (spec 87 — a globally granted role
    applies on every project, so its project-scoped atoms are live too)."""
    role_ids = set(
        (
            await session.execute(
                select(ProjectMember.role_id).where(
                    ProjectMember.project_id == project.id, ProjectMember.user_id == user_id
                )
            )
        ).scalars()
    )
    # Deferred import: auth loads before teams in the module assembly, so a top-level
    # import would re-enter half-initialized packages during startup.
    from radd.modules.teams import service as teams

    role_ids |= await teams.team_granted_role_ids(session, user_id, project.id)
    # Grants that apply here: global (every project) + those scoped to this project.
    role_ids |= await grants.granted_role_ids(session, user_id, project.id)
    return role_ids


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
        session, await _granted_role_ids(session, user_id, project)
    )


async def _global_permission_sets(
    session: AsyncSession, user_id: uuid.UUID
) -> list[Sequence[str]]:
    """The permission sets of every role granted to the user instance-wide (spec 87)."""
    return await _permission_sets_for_roles(session, await grants.granted_role_ids(session, user_id))


# --- the seam ---


async def effective_permissions(
    session: AsyncSession,
    user: User,
    *,
    project: Project | None = None,
) -> frozenset[Permission]:
    """The permission union the user effectively holds in the scope (empty = no access).

    Spec 86: two scopes only — a project, or global (project=None). Every
    active user is a member; inactive users hold nothing anywhere.
    """
    role = _active_role(user)
    if role is None:
        return frozenset()
    if InstanceRole(role) is InstanceRole.ADMIN:
        return all_permission_keys()
    if project is not None:
        permission_sets = await _project_permission_sets(session, user.id, project)
        return combine_permissions(
            instance_role=user.instance_role,
            permission_sets=permission_sets,
        )
    return global_scope_permissions(role, await _global_permission_sets(session, user.id))


async def require(
    session: AsyncSession,
    user: User,
    permission: Permission,
    *,
    project: Project | None = None,
) -> frozenset[Permission]:
    """Raise ForbiddenError (-> 403) unless the user holds `permission` in the scope.

    Returns the full effective-permission union so callers can reuse it (field-level
    visibility, response shaping) without a second lookup.
    """
    permissions = await effective_permissions(session, user, project=project)
    if permission not in permissions:
        if project is not None:
            raise ForbiddenError(f"permission '{permission}' denied on project {project.key}")
        raise ForbiddenError(f"permission '{permission}' denied")
    return permissions


# --- batched + downstream seams ---


async def permissions_for_projects(
    session: AsyncSession, user: User, projects: Sequence[Project]
) -> dict[uuid.UUID, frozenset[Permission]]:
    """Effective permissions for many projects in one batched pass (list hydration).

    One instance role decides the tier (admin -> all, active -> member floor +
    project grants, inactive -> nothing) for every project.
    """
    if not projects:
        return {}
    role = _active_role(user)
    if role is None:
        return {project.id: frozenset() for project in projects}
    if InstanceRole(role) is InstanceRole.ADMIN:
        return {project.id: all_permission_keys() for project in projects}

    project_ids = [project.id for project in projects]
    granted: dict[uuid.UUID, set[uuid.UUID]] = {project_id: set() for project_id in project_ids}
    direct = await session.execute(
        select(ProjectMember.project_id, ProjectMember.role_id).where(
            ProjectMember.user_id == user.id, ProjectMember.project_id.in_(project_ids)
        )
    )
    for project_id, role_id in direct.all():
        granted[project_id].add(role_id)
    from radd.modules.teams import service as teams  # deferred: teams loads after auth

    for project_id, role_ids in (
        await teams.team_granted_role_ids_for_projects(session, user.id, project_ids)
    ).items():
        granted[project_id] |= role_ids
    # Instance-wide grants (spec 87) apply on every project — one lookup, not N.
    global_role_ids = await grants.granted_role_ids(session, user.id)
    for role_ids in granted.values():
        role_ids |= global_role_ids
    # Project-scoped grants (spec 91) apply only on their project.
    for project_id, role_ids in (
        await grants.project_granted_role_ids(session, user.id, project_ids)
    ).items():
        granted[project_id] |= role_ids
    all_role_ids = {role_id for role_ids in granted.values() for role_id in role_ids}
    permissions_by_role: dict[uuid.UUID, list[str]] = {}
    if all_role_ids:
        rows = await session.execute(
            select(Role.id, Role.permissions).where(Role.id.in_(all_role_ids))
        )
        permissions_by_role = dict(rows.all())

    return {
        project.id: combine_permissions(
            instance_role=user.instance_role,
            permission_sets=[
                permissions_by_role.get(role_id, []) for role_id in granted[project.id]
            ],
        )
        for project in projects
    }


@dataclass(frozen=True)
class Subjects:
    """The grant subjects a user brings to a project — spec 07 (field grants) consumes this."""

    role_ids: frozenset[uuid.UUID]  # every role held on the project (direct + team-granted)
    team_ids: frozenset[uuid.UUID]  # the user's teams


async def subjects_for(session: AsyncSession, user: User, project: Project) -> Subjects:
    from radd.modules.teams import service as teams  # deferred: teams loads after auth

    role_ids = await _granted_role_ids(session, user.id, project)
    team_ids = await teams.user_team_ids(session, user.id)
    return Subjects(role_ids=frozenset(role_ids), team_ids=frozenset(team_ids))
