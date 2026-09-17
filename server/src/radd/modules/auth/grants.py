"""Scopeable role grants (spec 87 → spec 91 → RADD-832) — how a role reaches a
user, team, or directory GROUP outside project membership, at global OR
project scope.

Spec 87 introduced instance-wide grants (`global_role_grants`). Spec 91 adds a
nullable `project_id`: NULL = global (unchanged), set = the role held only on that
project. One table, one resolution path, one Grant Role dialog — "grant any role
at global or project scope". Resolution shape still mirrors
`teams.team_granted_role_ids`: collect role ids, load their permission sets, union.
"""

import uuid
from collections import defaultdict
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, NotFoundError
from radd.kernel import changes, registries
from radd.modules.events import service as events

from .models import GlobalRoleGrant, Role
from .schemas import GlobalGrantEntry
from .types import AuthEntity, AuthEvent, GrantScopeKind
from radd.clock import utcnow


async def _subject_condition(session: AsyncSession, user_id: uuid.UUID):
    """A grant belongs to the user directly, to one of their teams, or — since
    RADD-832 — to one of their TRANSITIVE directory groups (a role granted to a
    parent group reaches every nested member). Both closures are memoised per
    request (RADD-830). Since spec 121 "directly" includes the principal rows
    the actor stands in for (Anyone; Signed-in users when authenticated)."""
    from radd.modules.groups import service as groups  # deferred: loads after auth
    from radd.modules.teams import service as teams  # deferred: teams loads after auth

    from .principals import subject_user_ids  # auth-internal; no cycle

    team_ids = await teams.user_team_ids(session, user_id)
    group_ids = await groups.user_group_ids(session, user_id)
    # Spec 121: every actor also matches the Anyone principal's grants, every
    # real account the Signed-in users principal's — the ONE place role grants
    # learn the world exists (access grants: SubjectContext.subject_user_ids).
    condition = GlobalRoleGrant.user_id.in_(subject_user_ids(user_id))
    if team_ids:
        condition = condition | GlobalRoleGrant.team_id.in_(team_ids)
    if group_ids:
        condition = condition | GlobalRoleGrant.group_id.in_(group_ids)
    return condition


def _live():
    """RADD-820: expiry applies AT RESOLUTION — an expired grant is absent the
    moment it passes, never 'until the sweep next runs'."""

    now = utcnow()
    return GlobalRoleGrant.expires_at.is_(None) | (GlobalRoleGrant.expires_at > now)


def _unscoped():
    """The instance-wide grants — no scope of any kind. They apply everywhere."""
    return GlobalRoleGrant.project_id.is_(None) & GlobalRoleGrant.space_id.is_(None)


async def granted_role_ids(
    session: AsyncSession,
    user_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
    *,
    space_id: uuid.UUID | None = None,
) -> set[uuid.UUID]:
    """Role ids the user holds by grant, in one scope.

    Neither id = GLOBAL scope: only the unscoped grants. A project id, or a space
    id (RADD-791), = the unscoped grants (they apply everywhere) PLUS the ones
    bound to that thing. Consumed by authz at every scope.

    A space resolves through exactly this function and no other, which is the
    point: `page.read` on the Render space is the same kind of fact as
    `item.read` on a project, resolved by the same code, and a second path would
    be a second set of rules to keep in step.
    """
    subject = await _subject_condition(session, user_id)
    scope = _unscoped()
    if project_id is not None:
        scope = scope | (GlobalRoleGrant.project_id == project_id)
    if space_id is not None:
        scope = scope | (GlobalRoleGrant.space_id == space_id)
    result = await session.execute(
        select(GlobalRoleGrant.role_id).where(subject & scope & _live()).distinct()
    )
    return set(result.scalars())


async def project_granted_role_ids(
    session: AsyncSession, user_id: uuid.UUID, project_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, set[uuid.UUID]]:
    """Batch: {project_id: role_ids} for grants SCOPED to those projects (the global
    ones are added separately by the caller — they apply to every project)."""
    ids = set(project_ids)
    if not ids:
        return {}
    subject = await _subject_condition(session, user_id)
    rows = await session.execute(
        select(GlobalRoleGrant.project_id, GlobalRoleGrant.role_id).where(
            subject & GlobalRoleGrant.project_id.in_(ids) & _live()
        )
    )
    out: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for project_id, role_id in rows.all():
        out[project_id].add(role_id)
    return out


async def space_granted_role_ids(
    session: AsyncSession, user_id: uuid.UUID, space_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, set[uuid.UUID]]:
    """Batch: {space_id: role_ids} for grants SCOPED to those spaces (RADD-791).

    The `project_granted_role_ids` shape, for the other scope — the unscoped
    grants apply everywhere and are added once by the caller rather than joined
    per row. Listing spaces resolves every space at once, so the per-space
    lookup would otherwise be a query per row of the wiki nav.
    """
    ids = set(space_ids)
    if not ids:
        return {}
    subject = await _subject_condition(session, user_id)
    rows = await session.execute(
        select(GlobalRoleGrant.space_id, GlobalRoleGrant.role_id).where(
            subject & GlobalRoleGrant.space_id.in_(ids) & _live()
        )
    )
    out: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for space_id, role_id in rows.all():
        out[space_id].add(role_id)
    return out


async def attributed_rows_for_user(
    session: AsyncSession, user_id: uuid.UUID
) -> "list[tuple[GlobalRoleGrant, str, str | None, uuid.UUID | None]]":
    """Every grant reaching the user, each with the SUBJECT that carried it:
    (row, via, carrier_name, carrier_group_id) where via ∈ grant|team|group
    (RADD-833 — the inspector needs the carrier, and for groups the chain).
    A row that matches through several channels is attributed once, in
    direct → team → group order (the most legible carrier wins)."""
    from radd.modules.groups import service as groups  # deferred
    from radd.modules.teams import service as teams  # deferred

    team_ids = await teams.user_team_ids(session, user_id)
    group_ids = await groups.user_group_ids(session, user_id)
    condition = GlobalRoleGrant.user_id == user_id
    if team_ids:
        condition = condition | GlobalRoleGrant.team_id.in_(team_ids)
    if group_ids:
        condition = condition | GlobalRoleGrant.group_id.in_(group_ids)
    rows = list((await session.execute(select(GlobalRoleGrant).where(condition))).scalars())
    team_names = {t.id: t.name for t in (await teams.teams_by_ids(session, team_ids)).values()}
    group_names = {
        g.id: g.name for g in (await groups.groups_by_ids(session, group_ids)).values()
    }
    out: list[tuple[GlobalRoleGrant, str, str | None, uuid.UUID | None]] = []
    for row in rows:
        if row.user_id == user_id:
            out.append((row, "grant", None, None))
        elif row.team_id is not None and row.team_id in team_ids:
            out.append((row, "team", team_names.get(row.team_id), None))
        elif row.group_id is not None and row.group_id in group_ids:
            out.append((row, "group", group_names.get(row.group_id), row.group_id))
    return out


async def held_role_ids_anywhere(session: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    """Role ids reaching the user through ANY grant channel (direct, team,
    group) at ANY scope — the RADD-809 inspector's subject set. Before RADD-832
    this was direct grants only, so a role a TEAM held by grant never matched a
    role-subject resource grant in the inspector."""
    subject = await _subject_condition(session, user_id)
    result = await session.execute(
        select(GlobalRoleGrant.role_id).where(subject & _live()).distinct()
    )
    return set(result.scalars())


async def unscoped_role_ids(session: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    """The instance-wide role ids — the ones that apply in every scope."""
    subject = await _subject_condition(session, user_id)
    result = await session.execute(
        select(GlobalRoleGrant.role_id).where(subject & _unscoped() & _live()).distinct()
    )
    return set(result.scalars())


async def list_grants(session: AsyncSession, role_id: uuid.UUID) -> list[GlobalRoleGrant]:
    """The GLOBAL grants of a role (the Roles page's global-grants editor)."""
    result = await session.execute(
        select(GlobalRoleGrant).where(GlobalRoleGrant.role_id == role_id, _unscoped())
    )
    return list(result.scalars())


async def grants_for_subject(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None = None,
    team_id: uuid.UUID | None = None,
    group_id: uuid.UUID | None = None,
) -> list[GlobalRoleGrant]:
    """Every grant (any role, any scope) held DIRECTLY by one subject — the
    team/user/group Roles tab. Exactly one of user_id/team_id/group_id."""
    named = [x for x in (user_id, team_id, group_id) if x is not None]
    if len(named) != 1:
        raise ConflictError(AuthEntity.GLOBAL_GRANT, reason="exactly one subject required")
    if user_id is not None:
        condition = GlobalRoleGrant.user_id == user_id
    elif team_id is not None:
        condition = GlobalRoleGrant.team_id == team_id
    else:
        condition = GlobalRoleGrant.group_id == group_id
    result = await session.execute(
        select(GlobalRoleGrant).where(condition).order_by(GlobalRoleGrant.created_at)
    )
    return list(result.scalars())


async def grants_for_project(
    session: AsyncSession, project_id: uuid.UUID
) -> list[GlobalRoleGrant]:
    """Every grant bound to one project (RADD-929) — the project's Access screen.

    The `grants_for_space` shape for the other scope, and the read that replaces
    `project_members` + `project_teams`: those two tables expressed exactly this
    row (subject × role × project) and were unioned into the same
    `_granted_role_ids` result, so "who has access to this project" now has one
    answer instead of three lists that had to be read together.

    Instance-wide grants are deliberately excluded, same reasoning as spaces: the
    panel answers "who was given access to THIS project", and folding in
    everyone with a global role would make revoking look possible where it is
    not.
    """
    result = await session.execute(
        select(GlobalRoleGrant)
        .where(GlobalRoleGrant.project_id == project_id)
        .order_by(GlobalRoleGrant.created_at)
    )
    return list(result.scalars())


async def grants_for_space(
    session: AsyncSession, space_id: uuid.UUID
) -> list[GlobalRoleGrant]:
    """Every grant bound to one wiki space (RADD-793) — the space's Access panel.

    Deliberately NOT including the instance-wide grants that also apply here: the
    panel answers "who was given access to THIS space", and folding in everyone
    with a global wiki role would make revoking look possible where it is not.
    """
    result = await session.execute(
        select(GlobalRoleGrant)
        .where(GlobalRoleGrant.space_id == space_id)
        .order_by(GlobalRoleGrant.created_at)
    )
    return list(result.scalars())


async def role_referenced(session: AsyncSession, role_id: uuid.UUID) -> bool:
    """Does any grant (global or project) still hold this role? (role-deletion guard)"""
    row = await session.scalar(
        select(GlobalRoleGrant.id).where(GlobalRoleGrant.role_id == role_id).limit(1)
    )
    return row is not None


# --- grant-centric CRUD (the unified Grant Role dialog) -----------------------


async def _check_scope(
    session: AsyncSession, *, project_id: uuid.UUID | None, space_id: uuid.UUID | None
) -> None:
    """Refuse a grant bound to a scope that does not exist (RADD-892).

    The columns are auth's, so the pairs are listed here; whether an id is REAL
    is the scope owner's answer, read from the registry. A kind whose module is
    not loaded cannot be checked — the foreign key is then the only guard, which
    turns a bad id into a 500 rather than a 404, and that is the honest cost of
    the module being absent.
    """
    for kind, scope_id in (
        (GrantScopeKind.PROJECT, project_id),
        (GrantScopeKind.SPACE, space_id),
    ):
        if scope_id is None:
            continue
        spec = registries.grant_scopes.get(kind)
        if spec is None:
            continue
        if not await spec.exists(session, scope_id):
            raise NotFoundError(kind, scope_id)


async def create_grant(
    session: AsyncSession,
    role_id: uuid.UUID,
    *,
    user_id: uuid.UUID | None = None,
    team_id: uuid.UUID | None = None,
    group_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    space_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    expires_at=None,
) -> GlobalRoleGrant:
    """Grant a role to a user, team, or directory group (RADD-832) at a scope.
    No scope id = instance-wide; a project id or a space id (RADD-791) binds it
    to that one thing."""
    from radd.modules.groups import service as groups_service
    from radd.modules.teams import service as teams

    from . import roles as roles_service, service as users_service

    if len([x for x in (user_id, team_id, group_id) if x is not None]) != 1:
        raise ConflictError(AuthEntity.GLOBAL_GRANT, reason="exactly one subject required")
    if project_id is not None and space_id is not None:
        raise ConflictError(
            AuthEntity.GLOBAL_GRANT, reason="a grant has at most one scope"
        )
    await session.execute(select(Role.id).where(Role.id == role_id).with_for_update())
    role = await roles_service.get_role(session, role_id)
    if user_id is not None and user_id not in await users_service.users_by_ids(session, [user_id]):
        raise ConflictError(AuthEntity.GLOBAL_GRANT, reason=f"no such user {user_id}")
    if team_id is not None and (await teams.teams_by_ids(session, [team_id])).get(team_id) is None:
        raise ConflictError(AuthEntity.GLOBAL_GRANT, reason=f"no such team {team_id}")
    if group_id is not None and (
        await groups_service.groups_by_ids(session, [group_id])
    ).get(group_id) is None:
        raise ConflictError(AuthEntity.GLOBAL_GRANT, reason=f"no such group {group_id}")
    await _check_scope(session, project_id=project_id, space_id=space_id)
    # Guard duplicates (NULL scope columns aren't caught by the unique constraint).
    existing = await session.scalar(
        select(GlobalRoleGrant.id).where(
            GlobalRoleGrant.role_id == role_id,
            GlobalRoleGrant.user_id == user_id,
            GlobalRoleGrant.team_id == team_id,
            GlobalRoleGrant.group_id == group_id,
            GlobalRoleGrant.project_id.is_(None)
            if project_id is None
            else GlobalRoleGrant.project_id == project_id,
            GlobalRoleGrant.space_id.is_(None)
            if space_id is None
            else GlobalRoleGrant.space_id == space_id,
        )
    )
    if existing is not None:
        raise ConflictError(AuthEntity.GLOBAL_GRANT, reason="that grant already exists")
    grant = GlobalRoleGrant(
        role_id=role_id, user_id=user_id, team_id=team_id, group_id=group_id,
        project_id=project_id, space_id=space_id,
        expires_at=expires_at, granted_by=actor_id,
    )
    session.add(grant)
    await session.flush()
    await _emit(session, role.key, grant, "granted", actor_id)
    return grant


async def update_grant_role(
    session: AsyncSession, grant_id: uuid.UUID, role_id: uuid.UUID, actor_id: uuid.UUID | None
) -> GlobalRoleGrant:
    """Change WHICH role an existing grant confers, scope untouched (RADD-1103)
    — one intent, one row, one event, where delete+create needed two atoms and
    wrote two history entries for a role change."""
    from . import roles as roles_service

    grant = await session.get(GlobalRoleGrant, grant_id)
    if grant is None:
        raise NotFoundError(AuthEntity.GLOBAL_GRANT, grant_id)
    await session.execute(select(Role.id).where(Role.id.in_({grant.role_id, role_id})).order_by(Role.id).with_for_update())
    old_role = await roles_service.get_role(session, grant.role_id)
    new_role = await roles_service.get_role(session, role_id)
    grant.role_id = new_role.id
    await session.flush()
    await _emit(
        session, new_role.key, grant, "role changed", actor_id, previous_role=old_role.key
    )
    return grant


async def delete_grant(
    session: AsyncSession, grant_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> None:
    from . import roles as roles_service

    grant = await session.get(GlobalRoleGrant, grant_id)
    if grant is None:
        raise NotFoundError(AuthEntity.GLOBAL_GRANT, grant_id)
    await session.execute(select(Role.id).where(Role.id == grant.role_id).with_for_update())
    role = await roles_service.get_role(session, grant.role_id)
    await _emit(session, role.key, grant, "revoked", actor_id)
    await session.delete(grant)
    await session.flush()


async def _grant_description(
    session: AsyncSession, grant: GlobalRoleGrant, role_key: str
) -> dict[str, str]:
    """What an auditor reads for a grant: the subject's NAME, the scope's KEY —
    resolved at write time so the record survives the subject's deletion."""
    from radd.kernel import registries
    from radd.modules.groups import service as groups_service
    from radd.modules.projects import service as projects_service
    from radd.modules.teams import service as teams

    from . import service as users_service

    if grant.user_id is not None:
        user = (await users_service.users_by_ids(session, [grant.user_id])).get(grant.user_id)
        subject_type, subject = "user", (user.name if user else str(grant.user_id))
    elif grant.team_id is not None:
        team = (await teams.teams_by_ids(session, [grant.team_id])).get(grant.team_id)
        subject_type, subject = "team", (team.name if team else str(grant.team_id))
    else:
        group = (await groups_service.groups_by_ids(session, [grant.group_id])).get(grant.group_id)
        subject_type, subject = "group", (group.name if group else str(grant.group_id))
    if grant.project_id is not None:
        ref = await projects_service.project_ref(session, grant.project_id)
        scope = f"project {ref['key']}" if ref else f"project {grant.project_id}"
    elif grant.space_id is not None:
        spec = registries.entity_refs.get("page_space")
        ref = await spec.ref(session, grant.space_id) if spec is not None else None
        label = (ref or {}).get("name") or (ref or {}).get("slug") or str(grant.space_id)
        scope = f"space {label}"
    else:
        scope = "global"
    return {"role": role_key, "subject_type": subject_type, "subject": subject, "scope": scope}


async def _emit(
    session: AsyncSession,
    role_key: str,
    grant: GlobalRoleGrant,
    action: str,
    actor_id: uuid.UUID | None,
    *,
    previous_role: str | None = None,
    previous_expiry=None,
) -> None:
    # Spec 123: the grant as an added/removed entry on the role's history,
    # naming who and where; a role change is one removed + one added.
    description = await _grant_description(session, grant, role_key)
    if action == "expiry changed":
        diff = [{"field": "expires_at", "from": previous_expiry.isoformat() if previous_expiry else None, "to": grant.expires_at.isoformat() if grant.expires_at else None}]
    elif action == "granted":
        diff = [{"field": "grants", "added": [description], "removed": []}]
    elif action == "revoked":
        diff = [{"field": "grants", "added": [], "removed": [description]}]
    else:
        diff = [
            {
                "field": "grants",
                "added": [description],
                "removed": [{**description, "role": previous_role}],
            }
        ]
    await events.emit(
        session,
        event_type=AuthEvent.ROLE_UPDATED,
        entity_type=AuthEntity.ROLE,
        entity_id=grant.role_id,
        actor_id=actor_id,
        payload={
            "action": f"grant_{action}",
            "key": role_key,
            "subject": description["subject"],
            "scope": description["scope"],
            "user_id": str(grant.user_id) if grant.user_id else None,
            "team_id": str(grant.team_id) if grant.team_id else None,
            "group_id": str(grant.group_id) if grant.group_id else None,
            "project_id": str(grant.project_id) if grant.project_id else None,
            "space_id": str(grant.space_id) if grant.space_id else None,
        },
        changes=diff,
    )


async def replace_grants(
    session: AsyncSession,
    role_id: uuid.UUID,
    entries: list[GlobalGrantEntry],
    actor_id: uuid.UUID | None = None,
    expected_grant_ids: list[uuid.UUID] | None = None,
) -> list[GlobalRoleGrant]:
    """Full-state replace of who holds this role GLOBALLY (the Roles page editor).
    Only global grants (project_id NULL) are touched — project-scoped grants are
    managed grant-by-grant through the Grant Role dialog."""
    from radd.modules.groups import service as groups_service  # deferred
    from radd.modules.teams import service as teams  # deferred: teams loads after auth

    from . import roles as roles_service, service as users_service

    from .models import Role

    await session.execute(select(Role.id).where(Role.id == role_id).with_for_update())
    role = await roles_service.get_role(session, role_id)
    seen: set[tuple[str, uuid.UUID]] = set()
    for entry in entries:
        if entry.user_id is not None:
            key = ("user", entry.user_id)
        elif entry.team_id is not None:
            key = ("team", entry.team_id)
        else:
            key = ("group", entry.group_id)
        if key in seen:
            raise ConflictError(AuthEntity.GLOBAL_GRANT, reason=f"duplicate subject {key[1]}")
        seen.add(key)  # type: ignore[arg-type]
    user_ids = [e.user_id for e in entries if e.user_id is not None]
    found_users = await users_service.users_by_ids(session, user_ids)
    for user_id in user_ids:
        if user_id not in found_users:
            raise ConflictError(AuthEntity.GLOBAL_GRANT, reason=f"no such user {user_id}")
    team_ids = [e.team_id for e in entries if e.team_id is not None]
    found_teams = await teams.teams_by_ids(session, team_ids)
    for team_id in team_ids:
        if found_teams.get(team_id) is None:
            raise ConflictError(AuthEntity.GLOBAL_GRANT, reason=f"no such team {team_id}")
    group_ids = [e.group_id for e in entries if e.group_id is not None]
    found_groups = await groups_service.groups_by_ids(session, group_ids)
    for gid in group_ids:
        if found_groups.get(gid) is None:
            raise ConflictError(AuthEntity.GLOBAL_GRANT, reason=f"no such group {gid}")

    # Spec 123: full-state replace diffs as who gained and who lost the role.
    previous_rows = list(
        await session.scalars(
            select(GlobalRoleGrant).where(GlobalRoleGrant.role_id == role_id, _unscoped())
        )
    )
    if expected_grant_ids is not None and set(expected_grant_ids) != {r.id for r in previous_rows}:
        raise ConflictError(AuthEntity.GLOBAL_GRANT, reason="Role holders changed; reload before saving")
    previous = [await _grant_description(session, row, role.key) for row in previous_rows]
    # Retained subjects keep their identity, expiry and original attribution.
    # Saving another holder must never turn a temporary grant into a permanent one.
    existing = {(r.user_id, r.team_id, r.group_id): r for r in previous_rows}
    new_rows = []
    for entry in entries:
        key = (entry.user_id, entry.team_id, entry.group_id)
        row = existing.pop(key, None)
        if row is None:
            row = GlobalRoleGrant(
                role_id=role_id, user_id=entry.user_id, team_id=entry.team_id,
                group_id=entry.group_id, granted_by=actor_id,
            )
            session.add(row)
        new_rows.append(row)
    for row in existing.values():
        await session.delete(row)
    await session.flush()
    current = [await _grant_description(session, row, role.key) for row in new_rows]
    entry_diff = changes.collection_change("grants", previous, current)
    await events.emit(
        session,
        event_type=AuthEvent.ROLE_UPDATED,
        entity_type=AuthEntity.ROLE,
        entity_id=role.id,
        actor_id=actor_id,
        changes=[entry_diff] if entry_diff is not None else [],
        payload={
            "action": "global_grants_replaced",
            "key": role.key,
            "users": [str(u) for u in user_ids],
            "teams": [str(t) for t in team_ids],
        },
    )
    return await list_grants(session, role_id)


async def users_entitled_to_project(
    session: AsyncSession, project_id: uuid.UUID
) -> set[uuid.UUID]:
    """Every account entitled to a project through a GRANT (RADD-938).

    The reverse of the usual question. `effective_permissions` answers
    "what may this person do here", which is the wrong shape for a picker —
    asking it per row would be one resolution per account in the directory.
    This resolves the SET once: the grants that apply here (project-scoped plus
    instance-wide, which reach every project), flattened through their subjects.

    Entitlement means a grant, deliberately. It does NOT include the
    relationship-derived visibility of RADD-937 — someone who can see a project
    because they filed a ticket in it is not therefore a sensible assignee, and
    a picker that offered them would be recommending the thing this exists to
    warn about.

    Admins are not enumerated: they bypass every check and adding ~all of them
    to every picker's "has access" set would say less, not more.
    """
    from radd.modules.groups import service as groups_service  # deferred
    from radd.modules.teams import service as teams  # deferred

    rows = (
        await session.execute(
            select(GlobalRoleGrant).where(
                (GlobalRoleGrant.project_id == project_id) | _unscoped(),
                _live(),
            )
        )
    ).scalars()

    users: set[uuid.UUID] = set()
    team_ids: set[uuid.UUID] = set()
    group_ids: set[uuid.UUID] = set()
    for row in rows:
        if row.user_id is not None:
            users.add(row.user_id)
        elif row.team_id is not None:
            team_ids.add(row.team_id)
        elif row.group_id is not None:
            group_ids.add(row.group_id)
    for team_id in team_ids:
        users |= {u.id for u, _via in await teams.member_users_with_via(session, team_id)}
    if group_ids:
        users |= await groups_service.users_for_groups(session, group_ids)
    return users
