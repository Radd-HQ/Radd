"""Action RBAC — the single enforcement seam (specs 03/06/86).

A user's permissions in a scope are the union of the roles granted to them
(directly, via a team, or via a transitive directory group), the instance-wide
grants, and the Baseline role every active user holds. Instance admins hold
everything. This module is a facade over `authz_core` (the pure core + seam),
`authz_batch` (batched/cross-project resolvers) and `authz_explain` (the
provenance pass); what is defined here is the relations layer (RADD-823) and
row guards (spec 121).
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
    permission_sources as permission_sources,
    team_permission_sources as team_permission_sources,
)
from . import grants
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
# `relations_held` says WHICH qualifiers a set carries; these turn that into a
# WHERE clause (lists/counts/search) or a row verdict (gates). The registry says
# what each qualifier MEANS — only the owning module knows its columns.


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
# A per-row admission every reader passes whatever relation they hold (a
# restricted issue admits only the people on it). Composed INSIDE the primitives
# below, so every resolver built on them agrees without each one remembering.


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
    return await _row_admits(session, admitting, actor, row)


async def _row_admits(
    session: AsyncSession, specs: list, actor: "RelationActor", row: object
) -> bool:
    """Does any of `specs` hold for this row? Pure predicates answer free; the
    query-gated ones (`holds=None`, RADD-844) share ONE EXISTS against the row."""
    if any(spec.holds(actor, row) for spec in specs if spec.holds is not None):
        return True
    pending = [spec for spec in specs if spec.holds is None]
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

    guard = row_guard_filter(resource, actor)
    if RELATION_ANY in relations:
        return guard
    clauses = [spec.where(actor) for spec in _held_specs(resource, relations)]
    if not clauses:
        return false()
    held_clause = clauses[0] if len(clauses) == 1 else or_(*clauses)
    return held_clause if guard is None else and_(held_clause, guard)


def _held_specs(resource: str, relations: frozenset[str]) -> list:
    """Every spec a held relation CONTAINS (downward closure: any ⊃ team ⊃ own),
    so holding @team covers the @own rows too."""
    from radd.kernel import registries

    return [
        spec
        for key, spec in registries.relations_for(resource).items()
        if any(relation_contains(held, key) for held in relations)
    ]


def relation_holds_row(
    resource: str, relations: frozenset[str], actor: "RelationActor", row: object
) -> bool:
    """The SYNC gating form: does ANY held relation hold for this loaded row? A
    query-gated relation (`holds=None`) counts as NOT held — fail closed; use
    `relation_holds_row_async` to honour those. The row guard is checked first."""
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
    """The gating form for gates that can ask the database (RADD-844): a
    query-gated relation (membership in another table, like `@participant`) is
    answered against THIS row. The row guard is checked first."""
    if not await row_guard_holds_async(session, resource, actor, row):
        return False
    if RELATION_ANY in relations:
        return True
    return await _row_admits(session, _held_specs(resource, relations), actor, row)


async def relation_row_ids_holding(
    session: AsyncSession,
    resource: str,
    relations: frozenset[str],
    actor: "RelationActor",
    rows: "Sequence[object]",
) -> set[uuid.UUID]:
    """Batched gating (RADD-844): the ids among `rows` the relation set holds for.
    Query-gated relations fold into ONE query over the page of ids, and the row
    guard into one more — never a query per row."""
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

    role_ids = await grants.granted_role_ids(session, user.id, project.id)
    team_ids = await teams.user_team_ids(session, user.id)
    group_ids = await groups.user_group_ids(session, user.id)
    return Subjects(
        role_ids=frozenset(role_ids),
        team_ids=frozenset(team_ids),
        group_ids=frozenset(group_ids),
    )
