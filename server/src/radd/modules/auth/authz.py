"""Action RBAC — the single enforcement seam (spec 03, reworked by specs 06/86).

Roles are data (`roles` table: builtin admin/member/viewer + custom rows).
A user's effective permissions on a project are the UNION of:

- the roles granted to them directly, to a team they are on, or to a directory
  group that contains them (RADD-929 folded direct membership and team
  attachments into those grants — one table, one resolution path),
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

RADD-902: this module is now a FACADE. The pure decision core + the seam
(`effective_permissions`/`require`/`holds_base`) live in `authz_core.py`; the
batched/cross-project resolvers live in `authz_batch.py`; the `PermissionSource`
explain machinery lives in `authz_explain.py`. Everything those three modules
define is re-exported here under its own name, so every existing caller
(`from radd.modules.auth import authz` then `authz.require(...)`, or
`from radd.modules.auth.authz import Permission`) is unaffected. What's left
here in real code is the RELATIONS layer (RADD-823) — `relation_filter`/
`relation_holds_row`/`relation_row_ids_holding` and the `Subjects` resolver —
which sits on top of the core/batch/explain trio but nothing in that trio
depends on it, so it stays put rather than forming a fourth file for its own
sake.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.projects.models import Project

from .authz_batch import (
    _PROJECT_MAP_CACHE_KEY as _PROJECT_MAP_CACHE_KEY,
    _READABLE_CACHE_KEY as _READABLE_CACHE_KEY,
    holds as holds,
    permissions_for_projects as permissions_for_projects,
    permissions_for_spaces as permissions_for_spaces,
    project_permission_map as project_permission_map,
    readable_projects as readable_projects,
    require_anywhere as require_anywhere,
    require_member as require_member,
    visible_projects as visible_projects,
)
from .authz_core import (
    _BASELINE_CACHE_KEY as _BASELINE_CACHE_KEY,
    _REQUESTER_CACHE_KEY as _REQUESTER_CACHE_KEY,
    EMPTY_BASELINE as EMPTY_BASELINE,
    _active_role as _active_role,
    _global_permission_sets as _global_permission_sets,
    _granted_role_ids as _granted_role_ids,
    _narrow_to_key_scope as _narrow_to_key_scope,
    _permission_sets_for_roles as _permission_sets_for_roles,
    _project_permission_sets as _project_permission_sets,
    baseline_permissions as baseline_permissions,
    combine_permissions as combine_permissions,
    effective_permissions as effective_permissions,
    floor_permissions as floor_permissions,
    forget_baseline as forget_baseline,
    global_scope_permissions as global_scope_permissions,
    holds_base as holds_base,
    is_admin as is_admin,
    require as require,
)
from .authz_explain import (
    PermissionSource as PermissionSource,
    scope_labels as scope_labels,
    all_held_role_ids as all_held_role_ids,
    permission_sources as permission_sources,
    team_permission_sources as team_permission_sources,
)
from .models import User
from .principals import is_instance_admin as is_instance_admin
from .types import (
    RELATION_ANY,
    relation_contains,
    Permission,  # noqa: F401  — re-exported: every module imports Permission from here
    expand_permissions,  # noqa: F401  — re-exported: tests exercise the pure core directly
    relations_held,  # noqa: F401  — re-exported beside the resolvers below (RADD-823)
)

if TYPE_CHECKING:
    from radd.kernel.specs import RelationActor


# --- relations (RADD-823) -----------------------------------------------------
#
# The two resolver forms every adopter composes. `relations_held` (auth.types)
# answers WHICH qualifiers a permission set carries for a base atom; these turn
# that answer into a WHERE clause (lists/counts/search) or a row verdict
# (gates). The registry supplies what each qualifier MEANS — only the owning
# module knows its columns.


async def relation_actor(session: AsyncSession, user: User) -> "RelationActor":
    """The acting user as relation predicates see them. `team_ids` is the
    RADD-830 subject graph (direct + group-carried), memoised per request —
    a relation predicate must never re-derive it. `unrestricted` (spec 121)
    marks the instance admin, whom row guards do not bind (D1)."""
    from radd.kernel.specs import RelationActor
    from radd.modules.teams import service as teams  # deferred: teams loads after auth

    return RelationActor(
        user_id=user.id,
        team_ids=frozenset(await teams.user_team_ids(session, user.id)),
        unrestricted=is_instance_admin(user),
    )


# --- row guards (spec 121) ------------------------------------------------------
#
# A guard is a per-row admission every reader passes whatever relation they
# hold: a restricted issue admits only the people on it. Composed INSIDE the
# primitives below, so every resolver built on them — the item row filter, the
# gate, capabilities, notifications — agrees without each one remembering.


def _guard(resource: str):
    from radd.kernel import registries

    return registries.row_guards.get(resource)


def row_guard_filter(resource: str, actor: "RelationActor"):
    """FILTERING form of the guard: None when no guard binds this actor on
    this resource (none registered, or the actor is unrestricted); otherwise
    `open rows OR admitted-through-a-relation rows`."""
    from sqlalchemy import or_

    from radd.kernel import registries

    guard = _guard(resource)
    if guard is None or actor.unrestricted:
        return None
    specs = registries.relations_for(resource)
    arms = [guard.open_where()] + [
        specs[key].where(actor) for key in guard.admits if key in specs
    ]
    return arms[0] if len(arms) == 1 else or_(*arms)


def row_guard_holds(resource: str, actor: "RelationActor", row: object) -> bool:
    """SYNC gating form: open rows pass; guarded rows pass only through an
    admitting relation with a pure predicate (a query-gated one fails closed)."""
    from radd.kernel import registries

    guard = _guard(resource)
    if guard is None or actor.unrestricted or guard.open_holds(row):
        return True
    specs = registries.relations_for(resource)
    return any(
        specs[key].holds(actor, row)
        for key in guard.admits
        if key in specs and specs[key].holds is not None
    )


async def row_guard_holds_async(
    session: AsyncSession, resource: str, actor: "RelationActor", row: object
) -> bool:
    """Async gating form: like the sync one, then one EXISTS for the admitting
    relations whose membership lives in another table."""
    from radd.kernel import registries

    guard = _guard(resource)
    if guard is None or actor.unrestricted or guard.open_holds(row):
        return True
    specs = registries.relations_for(resource)
    admitting = [specs[key] for key in guard.admits if key in specs]
    if any(spec.holds(actor, row) for spec in admitting if spec.holds is not None):
        return True
    pending = [spec for spec in admitting if spec.holds is None]
    if not pending:
        return False
    from sqlalchemy import exists, or_, select

    model = type(row)
    clause = or_(*[spec.where(actor) for spec in pending])
    return bool(await session.scalar(select(exists().where(model.id == row.id, clause))))


def relation_filter(resource: str, relations: frozenset[str], actor: "RelationActor"):
    """The FILTERING form: None = unconstrained (`@any` held and no guard binds);
    otherwise the OR of the held relations' WHERE clauses — `false()` when
    nothing held, so an empty answer excludes rows instead of quietly passing
    them (fails closed). A qualifier with no registered spec contributes
    nothing (fails closed too: an unregistered relation must never widen).
    Spec 121: the resource's row guard is ANDed under every answer."""
    from sqlalchemy import and_, false, or_

    from radd.kernel import registries

    guard = row_guard_filter(resource, actor)
    if RELATION_ANY in relations:
        return guard
    specs = registries.relations_for(resource)
    # Downward closure (the lattice is normative: any ⊃ team ⊃ own) — holding
    # @team covers the @own rows too, so the filter ORs every CONTAINED spec.
    clauses = [
        spec.where(actor)
        for key, spec in specs.items()
        if any(relation_contains(held, key) for held in relations)
    ]
    if not clauses:
        return false()
    held_clause = clauses[0] if len(clauses) == 1 else or_(*clauses)
    return held_clause if guard is None else and_(held_clause, guard)


def _held_specs(resource: str, relations: frozenset[str]) -> list:
    from radd.kernel import registries

    return [
        spec
        for key, spec in registries.relations_for(resource).items()
        if any(relation_contains(held, key) for held in relations)
    ]


def relation_holds_row(
    resource: str, relations: frozenset[str], actor: "RelationActor", row: object
) -> bool:
    """The GATING form: does ANY held relation hold for this loaded row?

    SYNC — only pure predicates answer here. A query-gated relation
    (`holds=None`, RADD-844) is treated as NOT held: failing closed, never
    wide. A gate that must honour those uses `relation_holds_row_async`.
    Spec 121: the row guard is checked first, under every relation set."""
    if not row_guard_holds(resource, actor, row):
        return False
    if RELATION_ANY in relations:
        return True
    return any(
        spec.holds(actor, row) for spec in _held_specs(resource, relations)
        if spec.holds is not None
    )


async def relation_holds_row_async(
    session: AsyncSession,
    resource: str,
    relations: frozenset[str],
    actor: "RelationActor",
    row: object,
) -> bool:
    """The GATING form for gates that can ask the database (RADD-844): pure
    predicates answer free; a query-gated relation (`holds=None` — membership
    in another table, like `@participant`) is answered by running its
    where-form against THIS row's id. One EXISTS covers them all.
    Spec 121: the row guard is checked first, under every relation set."""
    if not await row_guard_holds_async(session, resource, actor, row):
        return False
    if RELATION_ANY in relations:
        return True
    held = _held_specs(resource, relations)
    if any(spec.holds(actor, row) for spec in held if spec.holds is not None):
        return True
    pending = [spec for spec in held if spec.holds is None]
    if not pending:
        return False
    from sqlalchemy import exists, or_, select

    model = type(row)
    clause = or_(*[spec.where(actor) for spec in pending])
    return bool(
        await session.scalar(select(exists().where(model.id == row.id, clause)))
    )


async def relation_row_ids_holding(
    session: AsyncSession,
    resource: str,
    relations: frozenset[str],
    actor: "RelationActor",
    rows: "Sequence[object]",
) -> set[uuid.UUID]:
    """Batched gating (RADD-844): the ids among `rows` the relation set holds
    for. Pure predicates run in Python; every query-gated relation is folded
    into ONE membership query over the page of ids — list surfaces stamping
    per-row capabilities stay one query, not one per row. Spec 121: the row
    guard is applied as one more batched predicate."""
    if not rows:
        return set()
    guard = row_guard_filter(resource, actor)
    if RELATION_ANY in relations:
        matched = {row.id for row in rows}
    else:
        held = _held_specs(resource, relations)
        matched = {
            row.id
            for row in rows
            if any(spec.holds(actor, row) for spec in held if spec.holds is not None)
        }
        pending = [spec for spec in held if spec.holds is None]
        remaining = [row for row in rows if row.id not in matched]
        if pending and remaining:
            from sqlalchemy import or_, select

            model = type(remaining[0])
            clause = or_(*[spec.where(actor) for spec in pending])
            result = await session.execute(
                select(model.id).where(model.id.in_([row.id for row in remaining]), clause)
            )
            matched.update(result.scalars())
    if guard is not None and matched:
        from sqlalchemy import select

        model = type(rows[0])
        admitted = await session.execute(
            select(model.id).where(model.id.in_(list(matched)), guard)
        )
        matched = set(admitted.scalars())
    return matched


@dataclass(frozen=True)
class Subjects:
    """The grant subjects a user brings to a project — spec 07 (field grants) consumes this."""

    role_ids: frozenset[uuid.UUID]  # every role held on the project (direct + team-granted)
    team_ids: frozenset[uuid.UUID]  # the user's teams (group-carried included, RADD-829)
    group_ids: frozenset[uuid.UUID]  # the user's transitive directory groups (RADD-830)


async def subjects_for(session: AsyncSession, user: User, project: Project) -> Subjects:
    from radd.modules.groups import service as groups  # deferred: loads after auth
    from radd.modules.teams import service as teams  # deferred: teams loads after auth

    role_ids = await _granted_role_ids(session, user.id, project)
    team_ids = await teams.user_team_ids(session, user.id)
    group_ids = await groups.user_group_ids(session, user.id)
    return Subjects(
        role_ids=frozenset(role_ids),
        team_ids=frozenset(team_ids),
        group_ids=frozenset(group_ids),
    )
