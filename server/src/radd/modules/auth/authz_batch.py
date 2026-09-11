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
    # RADD-929: two more queries used to run here — `project_members` and the
    # teams module's `project_teams` join — producing role ids the two grant
    # lookups below now produce on their own. Three tables, one fact; the batch
    # path lost a query per hydration along with the duplication.
    #
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
    unscoped = await grants.unscoped_role_ids(session, user.id)
    scoped = await grants.space_granted_role_ids(session, user.id, space_ids)
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
    """How a project earned its spot in a `visible_projects` map (RADD-1041).

    Presentation metadata ONLY — it explains a key that is already there, it
    never decides whether the key IS there. `GET /projects` threads this onto
    each row so the sidebar's per-user "related projects" preference can hide
    the RELATED half without touching security: `visible_projects` computes
    the exact same set of project ids it always has, tagged is all that's new.
    """

    #: `item.read` held UNQUALIFIED, i.e. by a grant. Theirs whether or not
    #: anything is in it yet.
    ENTITLED = "entitled"
    #: `item.read` held only in QUALIFIED form (own/participant/team) AND a
    #: real relationship exists. This is the half a requester's view of their
    #: own filed ticket depends on — see `visible_projects`.
    RELATED = "related"


@dataclass(frozen=True, slots=True)
class ProjectVisibility:
    """One `visible_projects` row: the resolved permission set plus WHY the
    project is in the map (RADD-1041). `via` is additive over the RADD-937
    resolution — dropping or hiding it must never change which projects
    appear, only how a caller chooses to DISPLAY them."""

    permissions: frozenset[Permission]
    via: ProjectVia


async def visible_projects(
    session: AsyncSession, user: User
) -> dict[uuid.UUID, ProjectVisibility]:
    """The projects this actor should be OFFERED (RADD-937), each tagged with
    WHY (RADD-1041).

    `require_anywhere(item.read)` answers "where could they read something",
    and `holds_base` counts a qualified atom as its base — correct, because
    `item.read@own` really does let them read their own rows there. Used as a
    LIST that made every project on the instance appear for an account holding
    nothing but the Baseline, since "your own rows, anywhere" covers everywhere.

    So visibility is the union of two different facts, each row's `via`
    (`ProjectVia`) names which one produced it:

    * **entitled** — `item.read` held UNQUALIFIED, i.e. by a grant. The project
      is theirs whether or not anything is in it.
    * **related** — held qualified AND the relationship is real: they have an
      item there, their team does, or they are a participant. This is what keeps
      a person's own tickets visible after every grant is revoked, which is the
      half that made emptying the Baseline unacceptable.

    Requiring the qualified read as well as the relationship is deliberate: with
    the own-item atoms removed from the Baseline, having an item somewhere
    confers nothing, because the actor cannot read it. The operator lever keeps
    working.

    The relationships come from the kernel registry, so this function names no
    module that produces one — `items` and `participants` contribute, and the
    next one does too without editing this.

    RADD-1041 threaded `via` through so a DISPLAY choice (the rail's "related
    projects" toggle) could be built without touching the SECURITY decision
    here: the key set below is identical to what this function returned before
    `via` existed — only the tag is new, and no caller may use it to filter who
    can reach a project.
    """
    reachable = await require_anywhere(session, user, Permission.ITEM_READ)
    entitled = {
        project_id: permissions
        for project_id, permissions in reachable.items()
        if Permission.ITEM_READ in permissions
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
