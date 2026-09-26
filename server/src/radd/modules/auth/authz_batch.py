"""Batched and cross-project resolvers; everything here calls into authz_core."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ForbiddenError
from radd.kernel import registries
from radd.modules.projects.models import Project

from . import grants
from .authz_core import (
    _active_role,
    _narrow_to_key_scope,
    combine_permissions,
    effective_permissions,
    floor_permissions,
    holds_base,
)
from .models import Role, User
from .types import GrantScopeKind, InstanceRole, Permission, all_permission_keys

#: Key prefix for the per-request memo of `readable_projects` (per actor).
_READABLE_CACHE_KEY = "radd.readable_projects"

#: Key prefix for the per-request memo of the full per-project permission map
#: (RADD-814) — the ladder's project tier, resolved once per actor per request.
_PROJECT_MAP_CACHE_KEY = "radd.project_permission_map"


async def permissions_for_projects(
    session: AsyncSession, user: User, projects: Sequence[Project]
) -> dict[uuid.UUID, frozenset[Permission]]:
    """Effective permissions for many projects in one batched pass (list hydration)."""
    return await _permissions_for_project_ids(session, user, [project.id for project in projects])


async def _permissions_for_project_ids(
    session: AsyncSession, user: User, project_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, frozenset[Permission]]:
    """Shared batch policy without hydrating unrelated project content."""
    if not project_ids:
        return {}
    role = _active_role(user)
    if role is None:
        return {project_id: frozenset() for project_id in project_ids}
    if InstanceRole(role) is InstanceRole.ADMIN:
        return {
            project_id: _narrow_to_key_scope(user, all_permission_keys(), project_id)
            for project_id in project_ids
        }

    granted: dict[uuid.UUID, set[uuid.UUID]] = {project_id: set() for project_id in project_ids}
    # Instance-wide grants (spec 87) apply on every project — one lookup, not N.
    global_role_ids = await grants.granted_role_ids(session, user.id)
    for role_ids in granted.values():
        role_ids |= global_role_ids
    # Project-scoped grants (spec 91) apply only on their project.
    for project_id, role_ids in (
        await grants.scoped_role_ids(session, user.id, GrantScopeKind.PROJECT, project_ids)
    ).items():
        granted[project_id] |= role_ids
    all_role_ids = {role_id for role_ids in granted.values() for role_id in role_ids}
    permissions_by_role: dict[uuid.UUID, list[str]] = {}
    if all_role_ids:
        rows = await session.execute(
            select(Role.id, Role.permissions).where(Role.id.in_(all_role_ids))
        )
        permissions_by_role = dict(rows.all())

    # Spec 113: the batched path must narrow too, or a scoped key would see the
    # full set anywhere a list hydrates permissions instead of resolving one project.
    baseline = await floor_permissions(session, user)
    return {
        project_id: _narrow_to_key_scope(
            user,
            combine_permissions(
                instance_role=user.instance_role,
                permission_sets=[
                    permissions_by_role.get(role_id, []) for role_id in granted[project_id]
                ],
                baseline=baseline,
            ),
            project_id,
        )
        for project_id in project_ids
    }


async def permissions_for_spaces(
    session: AsyncSession, user: User, space_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, frozenset[Permission]]:
    """Batch the direct space policy, including account floors and key scope.

    Keys currently carry global/project allowances. Space checks use their
    global allowance, exactly like effective_permissions(space_id=...). A
    project-only key cannot borrow page permissions from its account here.
    """
    if not space_ids:
        return {}
    role = _active_role(user)
    if role is None:
        return {space_id: frozenset() for space_id in space_ids}
    if InstanceRole(role) is InstanceRole.ADMIN:
        held = _narrow_to_key_scope(user, all_permission_keys(), None)
        return {space_id: held for space_id in space_ids}
    unscoped = await grants.granted_role_ids(session, user.id)
    scoped = await grants.scoped_role_ids(session, user.id, GrantScopeKind.SPACE, space_ids)
    role_ids = unscoped | {role_id for ids in scoped.values() for role_id in ids}
    by_role: dict[uuid.UUID, list[str]] = {}
    if role_ids:
        rows = await session.execute(
            select(Role.id, Role.permissions).where(Role.id.in_(role_ids))
        )
        by_role = dict(rows.all())
    floor = await floor_permissions(session, user)
    return {
        space_id: _narrow_to_key_scope(
            user,
            combine_permissions(
                instance_role=user.instance_role,
                permission_sets=[
                    by_role.get(role_id, [])
                    for role_id in unscoped | scoped.get(space_id, set())
                ],
                baseline=floor,
            ),
            None,
        )
        for space_id in space_ids
    }


class ProjectVia(StrEnum):
    """How a project earned its place in `visible_projects` (RADD-1041) —
    presentation only, never who may reach it."""

    ENTITLED = "entitled"  # item.read held unqualified (a grant)
    RELATED = "related"  # held only qualified AND a real relationship exists


@dataclass(frozen=True, slots=True)
class ProjectVisibility:
    """One `visible_projects` row: the permission set plus WHY the project is in
    the map. `via` never changes which projects appear, only how they display."""

    permissions: frozenset[Permission]
    via: ProjectVia


def _entitling_relation_held(permissions: frozenset[Permission], base: Permission) -> bool:
    """Spec 121: a ROW-PROPERTY relation (`@public`) entitles like the plain
    atom does — it says what the project shows, not who the actor is to a
    row — so a public project is offered to everyone who holds it, with no
    relationship required. Reads the kernel flag; names no relation."""
    from .types import relation_contains, relations_held, split_permission

    resource = split_permission(base)[0].split(".", 1)[0]
    held = relations_held(permissions, base)
    return any(
        spec.row_property and any(relation_contains(outer, key) for outer in held)
        for key, spec in registries.relations_for(resource).items()
    )


async def visible_projects(
    session: AsyncSession, user: User
) -> dict[uuid.UUID, ProjectVisibility]:
    """The projects this actor should be OFFERED (RADD-937), tagged with WHY.

    `require_anywhere(item.read)` is wrong for a list: `item.read@own` counts as
    the base, so a Baseline-only account would be offered every project. So:
      * ENTITLED — item.read held unqualified (or via a row-property relation such
        as @public), whether or not anything is in the project;
      * RELATED — held only qualified AND a real relationship exists (their item,
        their team's, a participation), from `registries.project_relations`.
    `via` is display metadata (RADD-1041); it never decides membership."""
    reachable = await require_anywhere(session, user, Permission.ITEM_READ)
    entitled = {
        project_id: permissions
        for project_id, permissions in reachable.items()
        if Permission.ITEM_READ in permissions
        or _entitling_relation_held(permissions, Permission.ITEM_READ)
    }
    qualified = {
        project_id: permissions
        for project_id, permissions in reachable.items()
        if project_id not in entitled
    }
    visible = {
        project_id: ProjectVisibility(permissions=permissions, via=ProjectVia.ENTITLED)
        for project_id, permissions in entitled.items()
    }
    if not qualified:
        return visible
    related: set[uuid.UUID] = set()
    for spec in registries.project_relations.values():
        related |= await spec.resolve(session, user)
    visible.update(
        {
            project_id: ProjectVisibility(permissions=permissions, via=ProjectVia.RELATED)
            for project_id, permissions in qualified.items()
            if project_id in related
        }
    )
    return visible


async def require_anywhere(
    session: AsyncSession, user: User, permission: Permission, *, refuse_when_empty: bool = False
) -> dict[uuid.UUID, frozenset[Permission]]:
    """The per-project permission map for every project where `permission` holds —
    the cross-project gate (RADD-672): a key scoped to one project never holds the
    GLOBAL atom, so cross-project reads ask this and constrain their query to the
    returned ids.

    Returns an empty map rather than raising (RADD-774): an empty list is an
    answer, a 403 is for acts. `refuse_when_empty=True` (the MCP tools) restores
    the 403, because an agent handed `[]` concludes there is nothing rather than
    that it may not look. Filters the request-memoised `project_permission_map`."""
    per_project = await project_permission_map(session, user)
    held = {
        pid: permissions
        for pid, permissions in per_project.items()
        if holds_base(permissions, permission)
    }
    if refuse_when_empty and not held and not holds_base(
        await effective_permissions(session, user), permission
    ):
        raise ForbiddenError(f"permission '{permission}' denied")
    return held


async def project_permission_map(
    session: AsyncSession, user: User
) -> dict[uuid.UUID, frozenset[Permission]]:
    """The effective union for EVERY project, memoised per request (RADD-814) —
    `require_anywhere`/`readable_projects` filter it."""
    key = f"{_PROJECT_MAP_CACHE_KEY}:{user.id}"
    cached: dict[uuid.UUID, frozenset[Permission]] | None = session.info.get(key)
    if cached is not None:
        return cached
    from radd.modules.projects import service as projects_service  # deferred: projects loads after auth

    project_ids = await projects_service.list_project_ids(session)
    resolved = await _permissions_for_project_ids(session, user, project_ids)
    session.info[key] = resolved
    return resolved


async def holds(
    session: AsyncSession,
    user: User,
    permission: Permission,
    *,
    project: Project | None = None,
    space_id: uuid.UUID | None = None,
    any_project: bool = False,
) -> bool:
    """THE boolean question under the ladder global ⊃ {project | space};
    `any_project` = held on at least one project or globally (RADD-672)."""
    if any_project:
        per_project = await project_permission_map(session, user)
        if any(holds_base(perms, permission) for perms in per_project.values()):
            return True
        return holds_base(await effective_permissions(session, user), permission)
    return holds_base(
        await effective_permissions(session, user, project=project, space_id=space_id),
        permission,
    )


async def readable_projects(
    session: AsyncSession, user: User
) -> dict[uuid.UUID, frozenset[Permission]]:
    """The projects this actor may read items in, memoised per request (RADD-788).

    Ask this — never `require(ITEM_READ)` with no project — for "is this a member
    of this instance?": grants are usually project-scoped, so a global check 403s
    real members. Project-scoped rows (views, dashboards, reports, worklogs) filter
    to these ids; instance-wide catalogs return [] when it is empty — emptiness,
    not a refusal (RADD-774)."""
    key = f"{_READABLE_CACHE_KEY}:{user.id}"
    cached: dict[uuid.UUID, frozenset[Permission]] | None = session.info.get(key)
    if cached is not None:
        return cached
    resolved = await require_anywhere(session, user, Permission.ITEM_READ)
    session.info[key] = resolved
    return resolved


async def require_member(
    session: AsyncSession, user: User
) -> dict[uuid.UUID, frozenset[Permission]]:
    """`readable_projects`, but a single-resource read has no empty answer, so
    this REFUSES when the actor holds item.read nowhere — no project and not
    globally (a fresh instance's admin has no projects yet, RADD-1132)."""
    readable = await readable_projects(session, user)
    if not readable and not holds_base(
        await effective_permissions(session, user), Permission.ITEM_READ
    ):
        raise ForbiddenError(f"permission '{Permission.ITEM_READ}' denied")
    return readable
