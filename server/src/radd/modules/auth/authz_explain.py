"""The `PermissionSource` explain machinery, split out of `authz.py`
(RADD-902) along its own marker (formerly lines 633+).

Enforcement (`authz_core.effective_permissions`) collapses every contributor
into a set; this is the deliberately SEPARATE second pass that answers "why
can this person do that?" — one atom, one provenance row — for the admin
inspector screens (RADD-779/809/833). Only `baseline_permissions` is shared
with the core; everything else here is self-contained.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.kernel import registries
from radd.modules.projects.models import Project

from . import grants
from .authz_core import baseline_permissions
from .models import Role, User
from .types import GrantScopeKind, InstanceRole, expand_permissions


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
    #: RADD-833 — the GROUP that carried it (via == "group"), and the nesting
    #: chain from the granted group down to the user's direct membership
    #: (["Render Wranglers", "VFX All", "Studio"] = a member 3 levels down).
    #: None chain = direct member of the granted group.
    via_group: str | None = None
    group_path: list[str] | None = None
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
        via_group: str | None = None,
        group_path: "list[str] | None" = None,
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
                via_group=via_group,
                group_path=group_path,
            )

    from .roles import role_by_key
    from .types import BuiltinRoleKey

    baseline_role = await role_by_key(session, BuiltinRoleKey.BASELINE)
    record(await baseline_permissions(session), kind="baseline", role_id=baseline_role.id)

    # (role_id, scope, via, via_team, via_group, group_path) per channel —
    # narrower scopes first. Grant channels are ATTRIBUTED to their carrying
    # subject (RADD-833): a group-held grant names the group AND the nesting
    # chain down to the user's direct membership, so "you have this because of
    # a group you have never heard of" reads as a path instead of a mystery.
    channels: list[
        tuple[uuid.UUID, str, str, str | None, str | None, list[str] | None]
    ] = []
    attributed = await grants.attributed_rows_for_user(session, user.id)

    async def _chain(group_id: uuid.UUID | None) -> list[str] | None:
        if group_id is None:
            return None
        from radd.modules.groups import service as groups_service  # deferred

        path = await groups_service.membership_path(session, user.id, group_id)
        return [g.name for g in path] if path else None

    if project is not None:
        # RADD-929: `project_members` and `project_teams` used to contribute two
        # more channels here. Both are grants now, so the `attributed` loop below
        # — which already knew how to name a direct / team / group carrier —
        # covers every route a role takes to this project.
        for row, via, carrier, carrier_group in attributed:
            if row.project_id == project.id:
                channels.append(
                    (
                        row.role_id,
                        "project",
                        via,
                        carrier if via == "team" else None,
                        carrier if via == "group" else None,
                        await _chain(carrier_group),
                    )
                )
    if space_id is not None:
        for row, via, carrier, carrier_group in attributed:
            if row.space_id == space_id:
                channels.append(
                    (
                        row.role_id,
                        "space",
                        via,
                        carrier if via == "team" else None,
                        carrier if via == "group" else None,
                        await _chain(carrier_group),
                    )
                )
    for row, via, carrier, carrier_group in attributed:
        if row.project_id is None and row.space_id is None:
            channels.append(
                (
                    row.role_id,
                    "global",
                    via,
                    carrier if via == "team" else None,
                    carrier if via == "group" else None,
                    await _chain(carrier_group),
                )
            )

    role_ids = {rid for rid, _, _, _, _, _ in channels}
    roles: dict[uuid.UUID, Role] = {}
    if role_ids:
        rows = await session.execute(select(Role).where(Role.id.in_(role_ids)))
        roles = {role.id: role for role in rows.scalars()}
    for rid, scope, via, via_team, via_group, group_path in channels:
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
            via_group=via_group,
            group_path=group_path,
        )

    return sorted(sources.values(), key=lambda s: s.permission)


async def team_permission_sources(session: AsyncSession, team_id: uuid.UUID) -> list[PermissionSource]:
    """What membership of this team confers (RADD-809) — the question a team
    owner actually has, and nothing answered before.

    Rows are NOT deduped across scopes the way the user view is: a role granted
    on project X and the same role granted on project Y are different facts, so
    uniqueness is (atom, role, scope label).
    """
    # RADD-929: `project_teams` used to contribute a second channel here, labelled
    # "attached", beside the grants. That is precisely the duplication this panel
    # made visible — one team's entitlement on one project listed twice under two
    # names — and both rows are grants now.
    project_ids: set[uuid.UUID] = set()
    grant_rows = await grants.grants_for_subject(session, team_id=team_id)
    for grant in grant_rows:
        if grant.project_id is not None:
            project_ids.add(grant.project_id)

    from radd.modules.projects import service as projects_service  # deferred

    keys = await projects_service.project_keys(session, project_ids) if project_ids else {}
    space_names = await scope_labels(
        session,
        GrantScopeKind.SPACE,
        {g.space_id for g in grant_rows if g.space_id is not None},
    )

    role_ids = {g.role_id for g in grant_rows}
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


async def scope_labels(
    session: AsyncSession, kind: GrantScopeKind, scope_ids: set[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """Display names for the things grants of `kind` are bound to (RADD-892).

    Read from the registered `GrantScopeSpec` rather than queried here: auth owns
    the `space_id` column but not what a space is CALLED, and reaching into
    `pages.models` for the name was the last non-spine model import in the
    codebase. An unregistered kind (its module disabled) yields no labels, which
    renders the scope unlabelled — the same degradation the old feature-detected
    import produced."""
    if not scope_ids:
        return {}
    spec = registries.grant_scopes.get(kind)
    if spec is None:
        return {}
    return await spec.labels(session, scope_ids)


async def all_held_role_ids(session: AsyncSession, user: User) -> set[uuid.UUID]:
    """Every role the user holds through ANY channel at ANY scope — the subject
    set the resource-access inspector matches role-subject grants against
    (RADD-809). Off the request path."""
    # RADD-832: every grant CHANNEL (direct, team, group), not just direct rows —
    # and since RADD-929 that is every channel there is, membership and team
    # attachment having become grants.
    return await grants.held_role_ids_anywhere(session, user.id)
