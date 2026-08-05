"""The batched + cross-project resolvers, split out of `authz.py` (RADD-902)
along its own "batched + downstream seams" marker (formerly lines 385+).

`permissions_for_projects` is the list-hydration batch path; `require_anywhere`/
`project_permission_map`/`holds`/`readable_projects`/`require_member` are the
cross-project tier built on top of it (RADD-672/774/814 — see each docstring).
Everything here calls into `authz_core.py` (the pure core + the seam) and
nothing else in the split; `authz.py` re-exports it all under its own name.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ForbiddenError
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
from .models import ProjectMember, Role, User
from .types import InstanceRole, Permission, all_permission_keys

#: Key prefix for the per-request memo of `readable_projects` (per actor).
_READABLE_CACHE_KEY = "radd.readable_projects"

#: Key prefix for the per-request memo of the full per-project permission map
#: (RADD-814) — the ladder's project tier, resolved once per actor per request.
_PROJECT_MAP_CACHE_KEY = "radd.project_permission_map"


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
        return {
            project.id: _narrow_to_key_scope(user, all_permission_keys(), project.id)
            for project in projects
        }

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

    # Spec 113: the batched path must narrow too, or a scoped key would see the
    # full set anywhere a list hydrates permissions instead of resolving one project.
    baseline = await floor_permissions(session, user)
    return {
        project.id: _narrow_to_key_scope(
            user,
            combine_permissions(
                instance_role=user.instance_role,
                permission_sets=[
                    permissions_by_role.get(role_id, []) for role_id in granted[project.id]
                ],
                baseline=baseline,
            ),
            project.id,
        )
        for project in projects
    }


async def require_anywhere(
    session: AsyncSession, user: User, permission: Permission, *, refuse_when_empty: bool = False
) -> dict[uuid.UUID, frozenset[Permission]]:
    """The per-project permission map for every project where `permission` holds.

    The cross-project gate (RADD-672). `require(permission)` with no project asks
    for the GLOBAL atom, which a spec-113 key scoped to one project never holds —
    so every cross-project read (GET /projects, un-scoped item listing, MCP
    search_items) refused exactly the principals the spec-114 catalog was built
    for. Holding the permission in ANY project satisfies this gate; the caller
    constrains its query to the returned project ids.

    **Does not raise by default** (RADD-774). An actor entitled to no project
    gets an empty map, which every list surface renders as an empty state. "There
    is nothing here for you" and "you did something you are not allowed to do"
    are different answers, and only the second deserves an error.

    `refuse_when_empty=True` restores the refusal, and the MCP tools pass it. The
    audiences genuinely differ: a person looking at an empty projects list can
    see that it is empty, whereas an AGENT handed `{"projects": []}` will
    conclude the instance has none and act on it. A refusal is the only way to
    tell a caller that has no eyes apart "you may not look" from "there is
    nothing there".

    This used to raise when the permission held nowhere, and that branch was
    unreachable: `item.read` sat in the hardcoded member floor, so every active
    user held it on every project. RADD-773 made the floor an editable Baseline
    role, and the first admin to remove `item.read` from it got a 403 on
    `GET /projects` — a permission toast as the greeting on a viewer-restricted
    instance.

    Nothing becomes readable: the atom still gates each project's contents. The
    only change is whether "you may see none of them" arrives as a result or as
    a failure.

    RADD-814: filters the request-memoised `project_permission_map`, so the
    seven cross-project surfaces that each used to run a projects listing plus
    a full batched resolution now share one.
    """
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
    """The effective union for EVERY project, memoised per request (RADD-814).

    The ladder's project tier, resolved once: `require_anywhere` and
    `readable_projects` are filters over this. Memoised beside
    `baseline_permissions` for the same reason — a page load crosses several
    cross-project surfaces, and each used to pay a projects listing plus a
    batched permission resolution of its own.
    """
    key = f"{_PROJECT_MAP_CACHE_KEY}:{user.id}"
    cached: dict[uuid.UUID, frozenset[Permission]] | None = session.info.get(key)
    if cached is not None:
        return cached
    from radd.modules.projects import service as projects_service  # deferred: projects loads after auth

    projects = await projects_service.list_projects(session)
    resolved = await permissions_for_projects(session, user, projects)
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
    """THE one boolean question, under the scope ladder (RADD-814):

        global  ⊃  {project | space}

    A grant at an outer scope satisfies a check at any scope it contains —
    which `effective_permissions` has always done by unioning global grants
    into every scoped resolution; this seam names it. `any_project` is the
    cross-project tier (RADD-672): held on at least one project, or globally.
    `require`/`require_anywhere` are the raising/map-returning forms of the
    same resolution — never a second opinion.
    """
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
    """THE member floor: the projects this actor may read items in (RADD-788).

    Ask this — never `require(ITEM_READ)` with no project — whenever a surface
    needs to know "is this an ordinary member of this instance?".

    ## Why the global check was wrong

    Roughly 28 endpoints used to gate on `item.read` at GLOBAL scope as a stand-in
    for membership. That check could not fail: `item.read` sat in the hardcoded
    `MEMBER_FLOOR`, so every active user held it globally and the gate was
    decoration — the same vacuous-gate class RADD-770 found on `page.write`.

    RADD-773 made the floor an editable Baseline role and made an absent one fail
    closed, both correctly. But a grant on this instance is normally SCOPED to a
    project, and a project-scoped grant contributes nothing at global scope — so
    the first admin to empty the Baseline turned every one of those gates into a
    hard 403 for people who were, in fact, members. `GET /views` was the one that
    decided the experience: specs 61–67 deleted the builtin board/list/planning
    pages, so refusing that list leaves a project with nothing in it.

    ## What callers do with the answer

    - **Rows scoped to a project** (views, dashboards, reports, worklogs): filter
      to these ids. That is the RADD-672 pattern and it is what makes an
      all-projects view show exactly the issues the viewer may see.
    - **Instance-wide catalogs** (labels, roles, teams, fields, cycles, work
      categories, canned responses): serve the catalog, and return an EMPTY list
      when this map is empty.

    Empty means "entitled to nothing anywhere", and it answers with emptiness
    rather than a refusal — RADD-774's rule. "There is nothing here for you" and
    "you did something you are not allowed to do" are different answers, and a
    new account landing on a wall of permission toasts is neither useful nor true.

    Memoised per request like `baseline_permissions`, and for the same reason: a
    page load hits several of these surfaces, each of which would otherwise repeat
    a projects listing plus a batched permission resolution. (RADD-814 moved the
    expensive half into `project_permission_map`, shared with every
    `require_anywhere` caller; this memo now caches only the filter.)
    """
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
    """`readable_projects`, but REFUSES when the actor is entitled to nothing.

    The same floor; the difference is what an empty answer can be expressed as.
    A LIST endpoint says "nothing here for you" by returning nothing, so it calls
    `readable_projects` and returns `[]`. A single-resource read has no such
    answer — a cycle either comes back or it does not — so this one raises.
    """
    readable = await readable_projects(session, user)
    if not readable:
        raise ForbiddenError(f"permission '{Permission.ITEM_READ}' denied")
    return readable
