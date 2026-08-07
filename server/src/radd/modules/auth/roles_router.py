"""Roles CRUD, the permission catalog, and role grants.

RADD-929 removed the `/projects/{id}/members` endpoints: direct membership is a
role grant scoped to the project, so `/role-grants` reads it (`?project_id=`) and
writes it, under the scope-derived authorization RADD-826 already built.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.projects import service as projects_service

from . import authz, preflight, grants, roles
from .deps import CurrentUser
from radd.exceptions import ConflictError, ForbiddenError

from .schemas import (
    BaselinePreflightRead,
    BaselinePreflightRequest,
    GlobalGrantRead,
    GlobalGrantsUpdate,
    PermissionRead,
    RoleCreate,
    RoleGrantCreate,
    RoleRead,
    RoleUpdate,
)
from pydantic import BaseModel

from .types import (
    AuthEntity,
    InstanceRole,
    Permission,
    expand_permissions,
    all_permission_keys,
    permission_description_of,
    permission_parts,
    permission_scope_of,
)

async def ensure_delegated_role_coverage(
    session: AsyncSession, actor, role, project
) -> None:
    """D14 (RADD-826): a DELEGATE cannot hand out atoms they do not hold — and
    the intersection is SCOPE-AWARE: "holds the atom at the scope of the grant
    being made". A project admin granting within their project passes on their
    project-scoped holdings; lacking an atom globally is not a refusal (without
    this, delegation mostly refuses). Relation-qualified atoms compare by the
    lattice: holding item.update (@any) covers granting item.update@own."""
    from .types import expand_permissions, relation_contains, relations_held, split_permission

    actor_permissions = await authz.effective_permissions(session, actor, project=project)
    missing: list[str] = []
    for atom in sorted(expand_permissions(set(role.permissions))):
        base, relation = split_permission(atom)
        held = relations_held(actor_permissions, base)
        if not any(relation_contains(h, relation) for h in held):
            missing.append(atom)
    if missing:
        shown = ", ".join(missing[:5]) + ("…" if len(missing) > 5 else "")
        raise ForbiddenError(
            f"'{role.key}' carries atoms you do not hold on {project.key}: {shown}"
        )


role_router = APIRouter(prefix="/roles", tags=["roles"])
role_grant_router = APIRouter(prefix="/role-grants", tags=["roles"])
permission_router = APIRouter(prefix="/permissions", tags=["roles"])

Session = Annotated[AsyncSession, Depends(get_session)]


@role_router.get("", response_model=list[RoleRead])
async def list_roles(session: Session, user: CurrentUser) -> list[RoleRead]:
    # RADD-816 (F6): the catalog read is a deliverable atom now — Baseline-
    # seeded, so day-one behaviour is the old member floor, but REVOCABLE.
    if not await authz.holds(session, user, Permission.ROLE_READ):
        return []
    return [RoleRead.model_validate(r) for r in await roles.list_roles(session)]


@role_router.post("", response_model=RoleRead, status_code=201)
async def create_role(data: RoleCreate, session: Session, user: CurrentUser) -> RoleRead:
    await authz.require(session, user, Permission.ROLE_CREATE)
    return RoleRead.model_validate(await roles.create_role(session, data, actor_id=user.id))


@role_router.post("/baseline/preflight", response_model=BaselinePreflightRead)
async def preflight_baseline(
    data: BaselinePreflightRequest, session: Session, user: CurrentUser
) -> BaselinePreflightRead:
    """RADD-825: "editing the Baseline to THIS would remove access for N users
    across M projects — here is who, and where." An editing aid, so it rides
    the editing gate; declared BEFORE /{role_id} (the RADD-761 shadowing rule).
    """
    await authz.require(session, user, Permission.ROLE_UPDATE)
    return await preflight.baseline_preflight(session, data.permissions)


@role_router.patch("/{role_id}", response_model=RoleRead)
async def update_role(
    role_id: uuid.UUID, data: RoleUpdate, session: Session, user: CurrentUser
) -> RoleRead:
    await authz.require(session, user, Permission.ROLE_UPDATE)
    return RoleRead.model_validate(await roles.update_role(session, role_id, data, actor_id=user.id))


@role_router.delete("/{role_id}", status_code=204)
async def delete_role(role_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    await authz.require(session, user, Permission.ROLE_DELETE)
    await roles.delete_role(session, role_id, actor_id=user.id)


_GRANTS_DOC = (
    "Who holds this role INSTANCE-WIDE (spec 87) — the delivery mechanism for global-scope "
    "atoms, which no project attachment can carry. Granted permissions apply at global scope "
    "and on every project. PUT replaces the full set atomically; each entry is exactly one of "
    "user_id/team_id/group_id. Gated on role.update: like editing a role's permission set, handing out "
    "instance-wide grants is escalation-equivalent to instance admin."
)


class RoleImpactRead(BaseModel):
    """RADD-836 U4: the blast radius of editing this role — how many people
    hold it through ANY channel. The Baseline answers "every active user"."""

    role_id: uuid.UUID
    total_users: int
    everyone: bool = False  # the Baseline: held by every active account


@role_router.get("/{role_id}/impact", response_model=RoleImpactRead)
async def role_impact(role_id: uuid.UUID, session: Session, user: CurrentUser) -> RoleImpactRead:
    """Who an edit to this role AFFECTS (RADD-836 U4) — resolved through every
    channel: direct membership rows, team attachments (group-carried members
    included), and role grants (user/team/group subjects, nesting resolved).
    A permission system that cannot answer this gets changed by trial and
    error on production."""
    await authz.require(session, user, Permission.ROLE_READ)
    role = await roles.get_role(session, role_id)
    from radd.modules.auth.types import BuiltinRoleKey

    if role.key == BuiltinRoleKey.BASELINE.value:
        from sqlalchemy import func, select as sa_select

        from .models import User as UserModel

        count = await session.scalar(
            sa_select(func.count()).select_from(UserModel).where(UserModel.active.is_(True))
        )
        return RoleImpactRead(role_id=role.id, total_users=count or 0, everyone=True)

    from sqlalchemy import select as sa_select

    from radd.modules.groups import service as groups_service
    from radd.modules.teams import service as teams_service

    from .models import GlobalRoleGrant

    # RADD-929: two more subject sources used to be read here (`project_members`
    # for users, `project_teams` for teams). Both are grants, so the loop below
    # collects every holder from one table.
    holders: set[uuid.UUID] = set()
    team_ids: set[uuid.UUID] = set()
    grant_rows = list(
        (
            await session.execute(
                sa_select(GlobalRoleGrant).where(GlobalRoleGrant.role_id == role_id)
            )
        ).scalars()
    )
    group_ids: set[uuid.UUID] = set()
    for grant in grant_rows:
        if grant.user_id is not None:
            holders.add(grant.user_id)
        elif grant.team_id is not None:
            team_ids.add(grant.team_id)
        elif grant.group_id is not None:
            group_ids.add(grant.group_id)
    for team_id in team_ids:
        holders |= {u.id for u, _via in await teams_service.member_users_with_via(session, team_id)}
    if group_ids:
        holders |= await groups_service.users_for_groups(session, group_ids)
    return RoleImpactRead(role_id=role.id, total_users=len(holders))


@role_router.get("/{role_id}/global-grants", response_model=list[GlobalGrantRead])
async def list_global_grants(
    role_id: uuid.UUID, session: Session, user: CurrentUser
) -> list[GlobalGrantRead]:
    await roles.get_role(session, role_id)
    await authz.require(session, user, Permission.ROLE_READ)
    return [GlobalGrantRead.model_validate(g) for g in await grants.list_grants(session, role_id)]


@role_router.put(
    "/{role_id}/global-grants", response_model=list[GlobalGrantRead], description=_GRANTS_DOC
)
async def replace_global_grants(
    role_id: uuid.UUID, data: GlobalGrantsUpdate, session: Session, user: CurrentUser
) -> list[GlobalGrantRead]:
    await authz.require(session, user, Permission.ROLE_UPDATE)
    rows = await grants.replace_grants(session, role_id, data.grants, actor_id=user.id)
    return [GlobalGrantRead.model_validate(g) for g in rows]


_GRANT_DIALOG_DOC = (
    "The unified Grant Role dialog (spec 91 → RADD-791 → RADD-832): grant a role to a "
    "user, team, or directory group "
    "at global scope (no ids), on specific projects, or in specific wiki spaces. One "
    "dialog for every scope — a second one for spaces is how two scopes become two sets "
    "of rules. Like editing a role, handing out grants is escalation-equivalent — gated "
    "on role.update."
)


@role_grant_router.get("", response_model=list[GlobalGrantRead])
async def list_role_grants(
    session: Session,
    user: CurrentUser,
    team_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    group_id: uuid.UUID | None = None,
    space_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
) -> list[GlobalGrantRead]:
    """Role grants, by SUBJECT (the team/user/group Roles tab), by SPACE
    (RADD-793), or by PROJECT (RADD-929).

    Exactly one of team_id/user_id/group_id/space_id/project_id. The scope
    directions are the ones an admin actually asks — "who has access to this
    space / this project?" — and asking that by walking every user was not an
    answer. The project direction replaces the `project_members` +
    `project_teams` reads: three lists that had to be read together to answer
    one question.
    """
    await authz.require_member(session, user)
    named = [x for x in (team_id, user_id, group_id, space_id, project_id) if x is not None]
    if len(named) != 1:
        raise ConflictError(
            AuthEntity.GLOBAL_GRANT,
            reason="exactly one of team_id/user_id/group_id/space_id/project_id",
        )
    if space_id is not None:
        rows = await grants.grants_for_space(session, space_id)
    elif project_id is not None:
        rows = await grants.grants_for_project(session, project_id)
    else:
        rows = await grants.grants_for_subject(
            session, user_id=user_id, team_id=team_id, group_id=group_id
        )
    return [GlobalGrantRead.model_validate(g) for g in rows]


@role_grant_router.post(
    "", response_model=list[GlobalGrantRead], status_code=201, description=_GRANT_DIALOG_DOC
)
async def create_role_grant(
    data: RoleGrantCreate, session: Session, user: CurrentUser
) -> list[GlobalGrantRead]:
    # RADD-826 (D3): a PROJECT admin grants existing roles on their own project
    # without global role.update — gated on member.create THERE, containment
    # enforced by the row shape (a delegate can only write project-scoped
    # grants) and D14's scope-aware intersection below.
    if not await authz.holds(session, user, Permission.ROLE_UPDATE):
        if not data.project_ids or data.space_ids:
            raise ForbiddenError(
                "granting beyond a project's scope requires role.update"
            )
        role = await roles.get_role(session, data.role_id)
        for project_id in data.project_ids:
            project = await projects_service.get_project(session, project_id)
            await authz.require(session, user, Permission.MEMBER_CREATE, project=project)
            await ensure_delegated_role_coverage(session, user, role, project)
    # (project_id, space_id) pairs — at most one of each is ever set. No ids at
    # all means one instance-wide grant, which is the spec-87 behaviour.
    scopes: list[tuple[uuid.UUID | None, uuid.UUID | None]] = [
        *((project_id, None) for project_id in data.project_ids),
        *((None, space_id) for space_id in data.space_ids),
    ] or [(None, None)]
    rows = [
        await grants.create_grant(
            session,
            data.role_id,
            user_id=data.user_id,
            team_id=data.team_id,
            group_id=data.group_id,
            project_id=project_id,
            space_id=space_id,
            actor_id=user.id,
            expires_at=data.expires_at.replace(tzinfo=None) if data.expires_at else None,
        )
        for project_id, space_id in scopes
    ]
    return [GlobalGrantRead.model_validate(g) for g in rows]


@role_grant_router.delete("/{grant_id}", status_code=204)
async def delete_role_grant(grant_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    # RADD-826: a project admin may revoke a grant SCOPED to their project
    # (member.delete there); anything wider still needs role.update.
    if not await authz.holds(session, user, Permission.ROLE_UPDATE):
        from .models import GlobalRoleGrant

        grant = await session.get(GlobalRoleGrant, grant_id)
        if grant is None or grant.project_id is None:
            raise ForbiddenError("revoking beyond a project's scope requires role.update")
        project = await projects_service.get_project(session, grant.project_id)
        await authz.require(session, user, Permission.MEMBER_DELETE, project=project)
    await grants.delete_grant(session, grant_id, actor_id=user.id)


class GrantHelpRead(BaseModel):
    """RADD-836 U3: who can actually fix a refusal — resolvable from the grant
    tables, so a 403 can name people instead of dead-ending."""

    permission: str
    scope: str
    granters: list[str]


@permission_router.get("/grant-help", response_model=GrantHelpRead)
async def grant_help(
    permission: str,
    session: Session,
    user: CurrentUser,
    project_id: uuid.UUID | None = None,
) -> GrantHelpRead:
    """Who can grant `permission` (RADD-836 U3): instance admins always; plus,
    for a project scope, the people holding member.create there (RADD-826's
    delegates). Names only — this is a door-knocker, not a directory."""
    await authz.require_member(session, user)
    from sqlalchemy import select as sa_select

    from radd.modules.auth.types import permission_scope_of

    from .models import User as UserModel

    admins = list(
        (
            await session.execute(
                sa_select(UserModel.name)
                .where(UserModel.instance_role == InstanceRole.ADMIN.value, UserModel.active.is_(True))
                .order_by(UserModel.name)
                .limit(10)
            )
        ).scalars()
    )
    granters = admins
    if project_id is not None:
        from radd.modules.projects import service as projects_service

        project = await projects_service.get_project(session, project_id)
        # RADD-929: the project's grants, not its membership rows. This read a
        # user-only table, so a delegate entitled through a team or a directory
        # group was never named — the 403 said "ask an admin" to people whose
        # own team lead could have fixed it.
        project_grants = await grants.grants_for_project(session, project.id)
        role_map = await roles.roles_by_ids(session, {g.role_id for g in project_grants})
        delegate_ids = [
            g.user_id
            for g in project_grants
            if g.user_id is not None
            if authz.holds_base(
                expand_permissions(set(role_map[g.role_id].permissions)),
                Permission.MEMBER_CREATE,
            )
        ]
        if delegate_ids:
            from . import service as users_service

            users_by_id = await users_service.users_by_ids(session, delegate_ids)
            granters = sorted(
                {*admins, *(u.name for u in users_by_id.values() if u.active)}
            )
    return GrantHelpRead(
        permission=permission,
        scope=permission_scope_of(permission).value,
        granters=granters[:10],
    )


@permission_router.get("", response_model=list[PermissionRead])
async def permission_catalog(session: Session, user: CurrentUser) -> list[PermissionRead]:
    """Every permission the system knows, with scope — for the admin role-matrix UI.
    VOCABULARY, not data (atom names and descriptions carry no instance state),
    so it stays on the member floor rather than role.read (RADD-816)."""
    await authz.require_member(session, user)
    # Composed from the kernel permissions registry (RADD-890): every atom's
    # scope and description is its owning module's declaration, whether that
    # module is `items` or a third-party plugin — there is no core/plugin branch
    # here, and there is nothing to edit in auth when a module adds one.
    #
    # The enum supplies DISPLAY ORDER only. It is a hand-curated grouping the
    # matrix reads top-to-bottom (item.* beside each other, the CRUD triples
    # after their umbrella), which sorting alphabetically would scatter; atoms
    # it does not name follow, sorted.
    ordered = [p.value for p in Permission]
    named = set(ordered)
    extra = sorted(k for k in all_permission_keys() if k not in named)
    catalog = []
    for key in [*ordered, *extra]:
        resource, action = permission_parts(key)
        catalog.append(
            PermissionRead(
                key=key,
                description=permission_description_of(key),
                scope=permission_scope_of(key),
                resource=resource,
                action=action,
            )
        )
    return catalog
