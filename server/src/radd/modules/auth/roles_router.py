"""Roles CRUD, the permission catalog, and role grants."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.apitypes import TOTAL_COUNT_HEADER
from radd.db import get_session
from radd.kernel import registries
from radd.modules.projects import service as projects_service

from . import authz, preflight, grants, roles, role_options, grant_directory, scoped_grants
from radd.choices import ChoiceRead
from .deps import CurrentUser
from radd.exceptions import ConflictError, ForbiddenError, NotFoundError

from .models import GlobalRoleGrant, User as UserModel
from .schemas import (
    BaselinePreflightRead,
    BaselinePreflightRequest,
    GlobalGrantRead,
    GrantDirectoryRead,
    SpaceGrantDirectoryRead,
    GlobalGrantsUpdate,
    PermissionRead,
    RelationOptionRead,
    RoleCreate,
    RoleGrantCreate,
    RoleGrantRoleUpdate,
    RoleRead,
    RoleUpdate,
)
from pydantic import BaseModel

from radd.modules.access.schemas import AccessGrantExpiry
from .types import (
    AuthEntity,
    BuiltinRoleKey,
    GrantScopeKind,
    InstanceRole,
    Permission,
    expand_permissions,
    all_permission_keys,
    permission_description_of,
    permission_parts,
    permission_scope_of,
    relation_contains,
    relations_held,
    split_permission,
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


async def _require_grant_delegate(
    session: AsyncSession,
    user,
    grant: GlobalRoleGrant | None,
    atom: Permission,
    refusal: str,
    *,
    role_id: uuid.UUID | None = None,
) -> None:
    """RADD-826: without role.update, a caller may touch only a PROJECT-scoped
    grant, holding `atom` there — and, when a role is being handed out, covering
    it (D14)."""
    if grant is None or grant.project_id is None:
        raise ForbiddenError(refusal)
    project = await projects_service.get_project(session, grant.project_id)
    await authz.require(session, user, atom, project=project)
    if role_id is not None:
        role = await roles.get_role(session, role_id)
        await ensure_delegated_role_coverage(session, user, role, project)


role_router = APIRouter(prefix="/roles", tags=["roles"])
role_grant_router = APIRouter(prefix="/role-grants", tags=["roles"])
permission_router = APIRouter(prefix="/permissions", tags=["roles"])

Session = Annotated[AsyncSession, Depends(get_session)]


@role_router.get("", response_model=list[RoleRead])
async def list_roles(session: Session, user: CurrentUser) -> list[RoleRead]:
    # RADD-816: role.read is Baseline-seeded but revocable.
    if not await authz.holds(session, user, Permission.ROLE_READ):
        return []
    return [RoleRead.model_validate(r) for r in await roles.list_roles(session)]


@role_router.get("/options", response_model=list[ChoiceRead])
async def role_choices(
    session: Session, user: CurrentUser, response: Response,
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    value: Annotated[str | None, Query(max_length=200)] = None,
    key: Annotated[str | None, Query(max_length=200)] = None,
) -> list[ChoiceRead]:
    rows, total = await role_options.list_options(
        session, user, q=q, limit=limit, offset=offset, value=value, key=key
    )
    response.headers[TOTAL_COUNT_HEADER] = str(total)
    return rows


@role_router.get("/assignable/options", response_model=list[ChoiceRead])
async def assignable_role_choices(
    session: Session, user: CurrentUser, response: Response,
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    value: Annotated[str | None, Query(max_length=200)] = None,
    project_id: uuid.UUID | None = None,
    space_id: uuid.UUID | None = None,
) -> list[ChoiceRead]:
    rows, total = await role_options.list_options(session, user, q=q, limit=limit, offset=offset, value=value, assignable=True, project_id=project_id, space_id=space_id)
    response.headers[TOTAL_COUNT_HEADER] = str(total)
    return rows


@role_grant_router.get("/by-space/{space_id}", response_model=list[SpaceGrantDirectoryRead])
async def space_grant_directory(
    space_id: uuid.UUID, session: Session, user: CurrentUser, response: Response,
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SpaceGrantDirectoryRead]:
    rows, total = await scoped_grants.page(session, user, space_id, GrantScopeKind.SPACE, q=q, limit=limit, offset=offset)
    response.headers[TOTAL_COUNT_HEADER] = str(total)
    return rows


@role_grant_router.get("/by-project/{project_id}", response_model=list[SpaceGrantDirectoryRead])
async def project_grant_directory(
    project_id: uuid.UUID, session: Session, user: CurrentUser, response: Response,
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SpaceGrantDirectoryRead]:
    rows, total = await scoped_grants.page(session, user, project_id, GrantScopeKind.PROJECT, q=q, limit=limit, offset=offset)
    response.headers[TOTAL_COUNT_HEADER] = str(total)
    return rows


@role_grant_router.get("/directory", response_model=list[GrantDirectoryRead])
async def subject_grant_directory(
    session: Session, user: CurrentUser, response: Response,
    team_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    group_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[GrantDirectoryRead]:
    rows, total = await grant_directory.subject_page(
        session, user, team_id=team_id, user_id=user_id, group_id=group_id,
        limit=limit, offset=offset,
    )
    response.headers[TOTAL_COUNT_HEADER] = str(total)
    return rows


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
    "Who holds this role INSTANCE-WIDE (spec 87): granted atoms apply at global scope and on "
    "every project. PUT replaces the full set atomically; each entry is exactly one of "
    "user_id/team_id/group_id. Gated on role.update — handing out instance-wide grants is "
    "escalation-equivalent to instance admin."
)


class RoleImpactRead(BaseModel):
    """RADD-836 U4: the blast radius of editing this role — how many people
    hold it through ANY channel. The Baseline answers "every active user"."""

    role_id: uuid.UUID
    total_users: int
    everyone: bool = False  # the Baseline: held by every active account


@role_router.get("/{role_id}/impact", response_model=RoleImpactRead)
async def role_impact(role_id: uuid.UUID, session: Session, user: CurrentUser) -> RoleImpactRead:
    """Who an edit to this role AFFECTS (RADD-836 U4): every holder through a
    user, team or (nested) group grant."""
    await authz.require(session, user, Permission.ROLE_READ)
    role = await roles.get_role(session, role_id)
    if role.key == BuiltinRoleKey.BASELINE.value:
        count = await session.scalar(
            sa_select(func.count()).select_from(UserModel).where(UserModel.active.is_(True))
        )
        return RoleImpactRead(role_id=role.id, total_users=count or 0, everyone=True)
    grant_rows = (
        await session.execute(sa_select(GlobalRoleGrant).where(GlobalRoleGrant.role_id == role_id))
    ).scalars()
    holders = await grants.holder_user_ids(session, grant_rows)
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
    rows = await grants.replace_grants(session, role_id, data.grants, actor_id=user.id, expected_grant_ids=data.expected_grant_ids)
    return [GlobalGrantRead.model_validate(g) for g in rows]


_GRANT_DIALOG_DOC = (
    "Grant a role to a user, team or directory group at global scope (no ids), on specific "
    "projects, or in specific wiki spaces (spec 91, RADD-791/832). Gated on role.update; a "
    "project delegate may grant existing roles on its own project (member.create there)."
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
    """Role grants by SUBJECT (the Roles tab), by SPACE (RADD-793) or by PROJECT
    (RADD-929); exactly one of team_id/user_id/group_id/space_id/project_id."""
    named = [x for x in (team_id, user_id, group_id, space_id, project_id) if x is not None]
    if len(named) != 1:
        raise ConflictError(
            AuthEntity.GLOBAL_GRANT,
            reason="exactly one of team_id/user_id/group_id/space_id/project_id",
        )
    if space_id is not None:
        # Wiki-only readers need no unrelated issue-project membership. Check
        # the requested space itself; unreadable grants must not be exposed.
        await authz.require(session, user, Permission.PAGE_READ, space_id=space_id)
        rows = await grants.grants_for_scope(session, GrantScopeKind.SPACE, space_id)
    else:
        await authz.require_member(session, user)
        if project_id is not None:
            await scoped_grants.require_project_scope(session, user, project_id)
            rows = await grants.grants_for_scope(session, GrantScopeKind.PROJECT, project_id)
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
    # RADD-826: a PROJECT admin grants existing roles on their own project with
    # member.create THERE — project-scoped rows only, plus D14's coverage check.
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


@role_grant_router.patch("/{grant_id}", response_model=GlobalGrantRead)
async def update_role_grant(
    grant_id: uuid.UUID, data: RoleGrantRoleUpdate, session: Session, user: CurrentUser
) -> GlobalGrantRead:
    """Change a grant's role in place (RADD-1103) — the operation member.update
    always advertised. Global-scope grants still need role.update; a
    project-scoped grant needs member.update THERE, and a delegate can only
    hand out roles their own coverage allows (the RADD-826 containment rule,
    same as create)."""
    if not await authz.holds(session, user, Permission.ROLE_UPDATE):
        await _require_grant_delegate(
            session,
            user,
            await session.get(GlobalRoleGrant, grant_id),
            Permission.MEMBER_UPDATE,
            "changing a grant beyond a project's scope requires role.update",
            role_id=data.role_id,
        )
    updated = await grants.update_grant_role(session, grant_id, data.role_id, actor_id=user.id)
    return GlobalGrantRead.model_validate(updated)


@role_grant_router.delete("/{grant_id}", status_code=204)
async def delete_role_grant(grant_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    if not await authz.holds(session, user, Permission.ROLE_UPDATE):
        await _require_grant_delegate(
            session,
            user,
            await session.get(GlobalRoleGrant, grant_id),
            Permission.MEMBER_DELETE,
            "revoking beyond a project's scope requires role.update",
        )
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
    """Who can grant `permission` (RADD-836 U3): instance admins, plus the
    member.create holders on the project (RADD-826). Names only."""
    await authz.require_member(session, user)
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
        project = await projects_service.get_project(session, project_id)
        project_grants = await grants.grants_for_scope(
            session, GrantScopeKind.PROJECT, project.id
        )
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
    VOCABULARY, not data (atom names and descriptions carry no instance state).
    Role/key managers also need it before any issue project exists. Ordinary
    readers retain the member floor; all management checks intersect credentials.
    """
    can_configure = any([
        await authz.holds(session, user, permission)
        for permission in (Permission.ROLE_CREATE, Permission.ROLE_UPDATE, Permission.SERVICE_ACCOUNT_UPDATE)
    ])
    if not can_configure:
        await authz.require_member(session, user)
    # Composed from the registry (RADD-890). The enum supplies DISPLAY ORDER only
    # (the matrix's hand-curated grouping); atoms it does not name follow, sorted.
    ordered = [p.value for p in Permission]
    named = set(ordered)
    extra = sorted(k for k in all_permission_keys() if k not in named)
    catalog = []
    for key in [*ordered, *extra]:
        resource, action = permission_parts(key)
        # RADD-939: the same relation-domain resolution the write validator uses.
        relations = registries.relations_for(registries.relation_domain(key))
        catalog.append(
            PermissionRead(
                key=key,
                description=permission_description_of(key),
                scope=permission_scope_of(key),
                resource=resource,
                action=action,
                relations=[
                    RelationOptionRead(key=relation_key, label=spec.label)
                    for relation_key, spec in sorted(relations.items())
                ],
            )
        )
    return catalog


@role_grant_router.patch("/{grant_id}/expiry", response_model=GlobalGrantRead)
async def change_role_grant_expiry(grant_id: uuid.UUID, data: AccessGrantExpiry, session: Session, user: CurrentUser):
    grant = await session.get(GlobalRoleGrant, grant_id)
    if grant is None:
        raise NotFoundError("role grant", grant_id)
    role = await roles.get_role(session, grant.role_id)
    if not await authz.holds(session, user, Permission.ROLE_UPDATE):
        await _require_grant_delegate(
            session,
            user,
            grant,
            Permission.MEMBER_UPDATE,
            "changing this grant requires role.update",
            role_id=role.id,
        )
    await grants.change_expiry(session, grant, role.key, data.expires_at, actor_id=user.id)
    return GlobalGrantRead.model_validate(grant)
