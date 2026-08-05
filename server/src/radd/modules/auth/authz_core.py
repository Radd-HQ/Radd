"""The pure decision core + THE enforcement seam, split out of `authz.py`
(RADD-902 — that file had grown past 1000 lines; this is its own "pure
decision core (86-273) / the seam (275-384)" markers, kept together here
because the seam calls straight into the core and `authz_batch.py`'s
`require_anywhere`/`holds` call the seam in turn — splitting the seam into
the facade instead would have made the facade and the batch module import
each other).

`combine_permissions`/`global_scope_permissions` are the pure union logic
(unit-tested directly); `floor_permissions`/`baseline_permissions` are the
thin, per-request-memoised DB reads beneath them; `effective_permissions`/
`require`/`holds_base` are the seam every other resolver (batched, explain,
relations) is built from. `authz.py` re-exports everything here under its
own name, so no caller anywhere changes.
"""

import uuid
from collections.abc import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ForbiddenError
from radd.modules.projects.models import Project

from . import grants
from .models import ProjectMember, Role, User
from .types import (
    BuiltinRoleKey,
    InstanceRole,
    Permission,
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

_REQUESTER_CACHE_KEY = "radd.requester_floor"


async def floor_permissions(session: AsyncSession, user: User) -> frozenset[Permission]:
    """The user's FLOOR (RADD-828): the Baseline for staff-shaped accounts, the
    seeded Requester role for email-provisioned ones (`UserSource.EMAIL`). The
    Baseline is the operator's STAFF policy row — handing it to every stranger
    whose mail was ingested would be a default-open hole, so the internet-facing
    floor is decoupled permanently. Same memoisation, same fail-closed default."""
    from .types import UserSource

    if getattr(user, "source", None) != UserSource.EMAIL.value:
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
    """Does the set hold `permission` in ANY form — unqualified or
    relation-qualified (RADD-823)? `item.read@own` HOLDS item.read (qualified);
    which qualifier is a second question (`relations_held`), asked by the
    surfaces that filter or gate rows. The fast path is the plain membership
    test every pre-relation role hits."""
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
