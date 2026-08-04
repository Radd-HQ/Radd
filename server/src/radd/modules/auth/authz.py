"""Action RBAC — the single enforcement seam (spec 03, reworked by specs 06/86).

Roles are data (`roles` table: builtin admin/member/viewer + custom rows).
A user's effective permissions on a project are the UNION of:

- the role their direct `project_members` row grants,
- the roles their teams' `project_teams` attachments grant,
- the roles granted to them instance-wide (`global_role_grants`, spec 87),
- the **Baseline role**, held by EVERY ACTIVE user without being granted
  (spec 86: being an active user of the server IS membership).

That last term used to be two hardcoded frozensets, and RADD-773 made it a
role. The difference that matters: an admin can now SEE it and change it. The
old constants meant three sources fed every check while Settings showed one, so
a member granted nothing anywhere could still edit any wiki page and delete any
cycle — and unchecking a permission in a role did nothing, because the floor was
unioned in afterwards.

Admins hold every permission. "Admin" means `users.instance_role == admin` —
THE one admin predicate (spec 86 stage 3 dropped the membership compat tier).
GLOBAL-scope checks (no project): admin -> all, active user -> the baseline
PLUS whatever their instance-wide role grants add, inactive -> nothing. Spec 87
added that last term: before it, a global-scope check read `instance_role`
alone, so every global atom the roles matrix offered (label.create,
team.update, sla.*, …) was ungrantable to a non-admin.

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
    expand_permissions,
)

# (RADD-814 removed the dead `ALL_PERMISSIONS` back-compat constant — the
# admin's effective set is `all_permission_keys()`, builtin ∪ plugin-registered,
# and the frozen enum copy silently excluded plugin atoms.)

# The floor is a ROLE now, not a constant (RADD-773).
#
# There used to be two frozensets here: MEMBER_FLOOR (what an active user held
# on every project) and MEMBER_GLOBAL_SCOPE (the same plus cycle.manage,
# timesheet.view and page.write at global scope). They were policy living in the
# kernel, and they were invisible: three sources of permission fed every check —
# the per-project floor, the global widening set, and actual role grants — while
# Settings showed only the third. A member who had been granted nothing anywhere
# could still delete cycles and edit any wiki page, and unchecking `item.read`
# in a role did nothing at all, because the floor was unioned in afterwards.
#
# What survives here is the MECHANISM — every active user holds a baseline. WHAT
# the baseline contains is `BuiltinRoleKey.BASELINE`, an ordinary editable row,
# which is why the combiners below take it as an argument instead of reading a
# constant. The seeded value is read-only (item.read + page.read); the three
# atoms it dropped are grantable through any role.
#
# The fallback below is used only when no baseline row exists yet — a database
# mid-migration, or a unit test exercising the pure core. It is deliberately the
# most restrictive answer rather than the old permissive one: a missing baseline
# must not silently reinstate the floor this change exists to remove.
EMPTY_BASELINE: frozenset[Permission] = frozenset()


# --- pure decision core (unit-tested) ---


def combine_permissions(
    *,
    instance_role: str,
    permission_sets: Iterable[Iterable[str]],
    baseline: Iterable[str] = EMPTY_BASELINE,
) -> frozenset[Permission]:
    """Union of the granted role permission sets, plus the baseline. Admins get all.

    `baseline` is the Baseline role's permissions (RADD-773) — what every active
    user holds without being granted anything. Passed in rather than read from a
    constant so that the answer is editable data and this stays a pure function.

    Atoms flow as strings (spec 93/A2): a role may grant a plugin-contributed atom
    that isn't a builtin `Permission` enum member, so we no longer coerce to the enum."""
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
    """Global-scope checks (spec 86): admin -> all, member (any active user) ->
    the baseline plus instance-wide grants, None (inactive) -> none.

    `permission_sets` (spec 87) are the sets of the roles granted to the user
    instance-wide — the only way a non-admin holds a global atom beyond the
    baseline.

    The SAME baseline feeds this and `combine_permissions` (RADD-773). There used
    to be a second, wider constant here, which is how `page.write` and
    `cycle.manage` came to be free for everyone with nothing on any screen saying
    so. One set, applied at both scopes: a project-scoped atom in it is inert
    globally and vice versa, which costs nothing and removes the pair that could
    drift apart.
    """
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


#: Key under which the request's baseline lookup is memoised on the session.
_BASELINE_CACHE_KEY = "radd.baseline_permissions"

#: Key prefix for the per-request memo of `readable_projects` (per actor).
_READABLE_CACHE_KEY = "radd.readable_projects"

#: Key prefix for the per-request memo of the full per-project permission map
#: (RADD-814) — the ladder's project tier, resolved once per actor per request.
_PROJECT_MAP_CACHE_KEY = "radd.project_permission_map"


async def baseline_permissions(session: AsyncSession) -> frozenset[Permission]:
    """What every active user holds without being granted anything (RADD-773).

    Read from the Baseline role row, so an admin editing it in Settings changes
    the answer — that is the entire point of the change. Memoised on
    `session.info`, i.e. for the life of one request: a permission check can run
    several times per request (a list hydrating per-project permissions runs it
    per project), and this must not become a query per check.

    An absent row answers EMPTY rather than falling back to the old floor. A
    missing baseline should fail closed; reinstating a permissive default here
    would quietly restore exactly what this replaced.
    """
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
    """Drop the memo — call after editing the Baseline role.

    Without this, the request that CHANGES the baseline goes on answering with
    the value it read before the write, so an admin's own confirming read would
    show the old set and the edit would look like it had not applied.
    """
    session.info.pop(_BASELINE_CACHE_KEY, None)


# --- the seam ---


async def effective_permissions(
    session: AsyncSession,
    user: User,
    *,
    project: Project | None = None,
    space_id: uuid.UUID | None = None,
) -> frozenset[Permission]:
    """The permission union the user effectively holds in the scope (empty = no access).

    Three scopes: a project, a wiki SPACE (RADD-791), or global (neither). Every
    active user is a member; inactive users hold nothing anywhere.

    The space scope exists because a page had none. Every `page.*` atom was
    checked globally, which made "let the render team read the render space"
    inexpressible and dropped page commenting entirely — the comments binding
    resolved `comment.write` with project=None, so a project-scoped grant never
    reached it. A space is a scope the way a project is; the difference is that a
    project also has membership rows and team attachments, while a space is
    reached by grant alone.
    """
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
            baseline=await baseline_permissions(session),
        )
    elif project is not None:
        permission_sets = await _project_permission_sets(session, user.id, project)
        resolved = combine_permissions(
            instance_role=user.instance_role,
            permission_sets=permission_sets,
            baseline=await baseline_permissions(session),
        )
    else:
        resolved = global_scope_permissions(
            role,
            await _global_permission_sets(session, user.id),
            baseline=await baseline_permissions(session),
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
    if permission not in permissions:
        if project is not None:
            raise ForbiddenError(f"permission '{permission}' denied on project {project.key}")
        if space_id is not None:
            raise ForbiddenError(f"permission '{permission}' denied in this space")
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
    baseline = await baseline_permissions(session)
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
        if permission in permissions
    }
    if refuse_when_empty and not held and permission not in await effective_permissions(session, user):
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
        if any(permission in perms for perms in per_project.values()):
            return True
        return permission in await effective_permissions(session, user)
    return permission in await effective_permissions(
        session, user, project=project, space_id=space_id
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


@dataclass(frozen=True)
class PermissionSource:
    """Where one atom came from (RADD-779).

    `effective_permissions` collapses every contributor into a set, which is the
    right answer for enforcement and the wrong one for "why can this person do
    that?" — the question that took reading `authz.py`, querying the live
    database and doing the union by hand, including the spec-50 umbrella
    expansions that turn one granted atom into four held ones.
    """

    #: The atom, e.g. "cycle.create".
    permission: str
    #: "baseline" | "role" | "instance-admin"
    kind: str
    #: The role that supplied it, when kind == "role".
    role_name: str | None = None
    #: True when the atom was not granted directly but implied by an umbrella
    #: (project.manage -> state.manage -> state.create). Without this the
    #: inspector would claim a role grants atoms its checkboxes never showed.
    implied: bool = False
    #: RADD-809 — the backlink: the role row that supplied the atom (the
    #: Baseline role's own id for kind == "baseline").
    role_id: uuid.UUID | None = None
    #: Where the supplying grant applies: "global" | "project" | "space".
    scope: str = "global"
    #: HOW the role reached this scope: "membership" (a project-member row),
    #: "team" (a team attached to the project), "grant" (a role grant),
    #: "attached" (team view: the team is attached to a project). None for
    #: baseline/instance-admin. RADD-833 extends this vocabulary with the
    #: group path.
    via: str | None = None
    #: The team that carried it, when via == "team".
    via_team: str | None = None
    #: Display name of the scoped project/space (team view rows span many).
    scope_label: str | None = None


async def permission_sources(
    session: AsyncSession,
    user: User,
    *,
    project: Project | None = None,
    space_id: uuid.UUID | None = None,
) -> list[PermissionSource]:
    """Every atom the user holds in the scope, each with its provenance.

    Deliberately a SECOND pass over the same inputs rather than a richer
    `effective_permissions`: enforcement runs on every request and must stay a
    set union, while this runs when an admin opens one person's row. Keeping
    them apart means the explanation can never slow the check down — and the
    explanation is derived from the same helpers, so it cannot describe a rule
    the resolver does not follow.

    RADD-809: takes a SPACE scope too (no `page.*` atom was explainable
    before), and each row carries the channel — membership, team attachment,
    grant — its scope, and the source role's id as a backlink. Narrower
    channels are recorded first, so an atom held both ways reads as the
    scoped fact.
    """
    if project is not None and space_id is not None:
        raise ValueError("inspect a project or a space, not both")
    if not user.active:
        return []
    if InstanceRole(user.instance_role) is InstanceRole.ADMIN:
        # One row, not ninety. An admin holds everything BECAUSE they are an
        # admin; listing each atom as though it were granted would bury that.
        return [PermissionSource(permission="*", kind="instance-admin")]

    sources: dict[str, PermissionSource] = {}

    def record(
        atoms: Iterable[str],
        *,
        kind: str,
        role_name: str | None = None,
        role_id: uuid.UUID | None = None,
        scope: str = "global",
        via: str | None = None,
        via_team: str | None = None,
    ) -> None:
        direct = {str(a) for a in atoms}
        for atom in sorted(expand_permissions(direct)):
            key = str(atom)
            if key in sources:
                continue
            sources[key] = PermissionSource(
                permission=key,
                kind=kind,
                role_name=role_name,
                implied=key not in direct,
                role_id=role_id,
                scope=scope,
                via=via,
                via_team=via_team,
            )

    from .roles import role_by_key
    from .types import BuiltinRoleKey

    baseline_role = await role_by_key(session, BuiltinRoleKey.BASELINE)
    record(await baseline_permissions(session), kind="baseline", role_id=baseline_role.id)

    # (role_id, scope, via, via_team) per channel — narrower scopes first.
    channels: list[tuple[uuid.UUID, str, str, str | None]] = []
    if project is not None:
        member_rows = await session.execute(
            select(ProjectMember.role_id).where(
                ProjectMember.user_id == user.id, ProjectMember.project_id == project.id
            )
        )
        channels += [(rid, "project", "membership", None) for rid in member_rows.scalars()]
        from radd.modules.teams import service as teams  # deferred: teams loads after auth

        for team_name, rid in await teams.team_role_pairs_for_project(
            session, user.id, project.id
        ):
            channels.append((rid, "project", "team", team_name))
        scoped = await grants.project_granted_role_ids(session, user.id, [project.id])
        channels += [(rid, "project", "grant", None) for rid in scoped.get(project.id, set())]
    if space_id is not None:
        scoped = await grants.space_granted_role_ids(session, user.id, [space_id])
        channels += [(rid, "space", "grant", None) for rid in scoped.get(space_id, set())]
    channels += [
        (rid, "global", "grant", None)
        for rid in await grants.granted_role_ids(session, user.id)
    ]

    role_ids = {rid for rid, _, _, _ in channels}
    roles: dict[uuid.UUID, Role] = {}
    if role_ids:
        rows = await session.execute(select(Role).where(Role.id.in_(role_ids)))
        roles = {role.id: role for role in rows.scalars()}
    for rid, scope, via, via_team in channels:
        role = roles.get(rid)
        if role is None:
            continue
        record(
            role.permissions,
            kind="role",
            role_name=role.name,
            role_id=role.id,
            scope=scope,
            via=via,
            via_team=via_team,
        )

    return sorted(sources.values(), key=lambda s: s.permission)


async def team_permission_sources(session: AsyncSession, team_id: uuid.UUID) -> list[PermissionSource]:
    """What membership of this team confers (RADD-809) — the question a team
    owner actually has, and nothing answered before.

    Rows are NOT deduped across scopes the way the user view is: a role
    attached on project X and a role granted on project Y are different facts,
    so uniqueness is (atom, role, scope label).
    """
    from radd.modules.teams import service as teams  # deferred: teams loads after auth

    channels: list[tuple[uuid.UUID, str, str, str | None]] = []
    project_ids: set[uuid.UUID] = set()
    for project_id, role_id in await teams.team_project_role_rows(session, team_id):
        channels.append((role_id, "project", "attached", None))
        project_ids.add(project_id)
    attach_rows = await teams.team_project_role_rows(session, team_id)
    grant_rows = await grants.grants_for_subject(session, team_id=team_id)
    for grant in grant_rows:
        if grant.project_id is not None:
            project_ids.add(grant.project_id)

    from radd.modules.projects import service as projects_service  # deferred

    keys = await projects_service.project_keys(session, project_ids) if project_ids else {}
    space_names = await _space_names(
        session, {g.space_id for g in grant_rows if g.space_id is not None}
    )

    role_ids = {rid for rid, _, _, _ in channels} | {g.role_id for g in grant_rows}
    roles: dict[uuid.UUID, Role] = {}
    if role_ids:
        rows = await session.execute(select(Role).where(Role.id.in_(role_ids)))
        roles = {role.id: role for role in rows.scalars()}

    sources: dict[tuple[str, uuid.UUID, str | None], PermissionSource] = {}

    def record(
        role: Role, *, scope: str, via: str, scope_label: str | None
    ) -> None:
        direct = {str(a) for a in role.permissions}
        for atom in sorted(expand_permissions(direct)):
            key = (str(atom), role.id, scope_label)
            if key in sources:
                continue
            sources[key] = PermissionSource(
                permission=str(atom),
                kind="role",
                role_name=role.name,
                implied=str(atom) not in direct,
                role_id=role.id,
                scope=scope,
                via=via,
                scope_label=scope_label,
            )

    for project_id, role_id in attach_rows:
        role = roles.get(role_id)
        if role is not None:
            record(role, scope="project", via="attached", scope_label=keys.get(project_id))
    for grant in grant_rows:
        role = roles.get(grant.role_id)
        if role is None:
            continue
        if grant.space_id is not None:
            scope, label = "space", space_names.get(grant.space_id)
        elif grant.project_id is not None:
            scope, label = "project", keys.get(grant.project_id)
        else:
            scope, label = "global", None
        record(role, scope=scope, via="grant", scope_label=label)

    return sorted(sources.values(), key=lambda s: (s.permission, s.scope_label or ""))


async def _space_names(session: AsyncSession, space_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Wiki-space display names, feature-detected (pages is an optional module)."""
    if not space_ids:
        return {}
    try:
        from radd.modules.pages.models import PageSpace
    except ImportError:
        return {}
    rows = await session.execute(
        select(PageSpace.id, PageSpace.name).where(PageSpace.id.in_(space_ids))
    )
    return dict(rows.all())


async def all_held_role_ids(session: AsyncSession, user: User) -> set[uuid.UUID]:
    """Every role the user holds through ANY channel at ANY scope — the subject
    set the resource-access inspector matches role-subject grants against
    (RADD-809). Off the request path."""
    from radd.modules.teams import service as teams  # deferred: teams loads after auth

    member_rows = await session.execute(
        select(ProjectMember.role_id).where(ProjectMember.user_id == user.id).distinct()
    )
    held = set(member_rows.scalars())
    held |= await teams.team_granted_role_ids_anywhere(session, user.id)
    grant_rows = await grants.grants_for_subject(session, user_id=user.id)
    held |= {g.role_id for g in grant_rows}
    return held


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
