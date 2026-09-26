"""The provenance pass behind the admin inspector (RADD-779/809/833): one row
per held atom, with where it came from."""

import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.kernel import registries
from radd.modules.projects.models import Project

from . import grants
from .authz_core import baseline_permissions
from .models import GlobalRoleGrant, Role, User
from .types import GrantScopeKind, InstanceRole, expand_permissions


@dataclass(frozen=True)
class PermissionSource:
    """Where one atom came from (RADD-779)."""

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
    #: HOW the role reached the scope: "grant" (held directly) | "team" | "group";
    #: None for baseline/instance-admin.
    via: str | None = None
    #: The team that carried it, when via == "team".
    via_team: str | None = None
    #: RADD-833 — the GROUP that carried it (via == "group"), and the nesting chain
    #: from the granted group down to the user's direct membership (None = direct).
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
    """Every atom the user holds in the scope, with its provenance (RADD-779/809).
    A deliberately separate pass from `effective_permissions`, built on the same
    helpers: enforcement stays a set union, this runs when an admin opens a row.
    Narrower channels are recorded first, so an atom held both ways reads as the
    scoped fact."""
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

    # (role_id, scope, via, via_team, via_group, group_path) per channel, narrower
    # scopes first; each grant is attributed to its carrying subject (RADD-833).
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

    scopes: list[tuple[str, Callable[[GlobalRoleGrant], bool]]] = []
    if project is not None:
        scopes.append(("project", lambda row: row.project_id == project.id))
    if space_id is not None:
        scopes.append(("space", lambda row: row.space_id == space_id))
    scopes.append(("global", lambda row: row.project_id is None and row.space_id is None))
    for scope, applies in scopes:
        for row, via, carrier, carrier_group in attributed:
            if applies(row):
                channels.append(
                    (
                        row.role_id,
                        scope,
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
    """What membership of this team confers (RADD-809). Not deduped across
    scopes: the same role on two projects is two facts."""
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
    """Display names for grant scopes of `kind`, from the registered
    GrantScopeSpec (auth does not know what a space is called); an unregistered
    kind yields none."""
    if not scope_ids:
        return {}
    spec = registries.grant_scopes.get(kind)
    if spec is None:
        return {}
    return await spec.labels(session, scope_ids)
