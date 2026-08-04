import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import get_session
from radd.exceptions import ForbiddenError, UnauthorizedError

from . import authz, roles as roles_service, service, service_accounts, totp
from .deps import CurrentUser
from .models import User
from .schemas import (
    AccessSummaryRead,
    ServiceAccountCreate,
    ServiceAccountRead,
    ServiceAccountUpdate,
    DuplicateUserGroup,
    LoginRequest,
    MeRead,
    ProfileUpdate,
    ResourceTypeAccessRead,
    TokenCreate,
    TokenCreated,
    TokenRead,
    TotpCodeRequest,
    TotpLoginRequest,
    TotpSetupRead,
    TotpStatusRead,
    UserAccessRead,
    UserAdminUpdate,
    PermissionSourceRead,
    UserContentSummary,
    UserCreate,
    UserDirectoryEntry,
    UserMergeRequest,
    UserRead,
)
from .types import SESSION_COOKIE_NAME, InstanceRole, UserSource

# The 401 detail the login form keys on to show the code field (spec 48).
TOTP_REQUIRED = "totp_required"

auth_router = APIRouter(prefix="/auth", tags=["auth"])
user_router = APIRouter(prefix="/users", tags=["users"])
token_router = APIRouter(prefix="/tokens", tags=["tokens"])

Session = Annotated[AsyncSession, Depends(get_session)]


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
    )


@auth_router.post("/login", status_code=204)
async def login(data: LoginRequest, session: Session, response: Response) -> None:
    user = await service.authenticate(session, data.email, data.password)
    if await service.totp_required(session, user):
        # No cookie yet — the client repeats via /login/totp with a code.
        raise UnauthorizedError(TOTP_REQUIRED)
    _set_session_cookie(response, await service.create_session(session, user))


@auth_router.post("/login/totp", status_code=204)
async def login_totp(data: TotpLoginRequest, session: Session, response: Response) -> None:
    """Second MFA step (spec 48): stateless — password re-verified with the code."""
    user = await service.authenticate_with_totp(session, data.email, data.password, data.code)
    _set_session_cookie(response, await service.create_session(session, user))


@auth_router.get("/totp", response_model=TotpStatusRead)
async def totp_status(user: CurrentUser, session: Session) -> TotpStatusRead:
    row = await service.totp_row(session, user.id)
    return TotpStatusRead(
        enabled=row is not None and row.confirmed_at is not None,
        pending=row is not None and row.confirmed_at is None,
    )


@auth_router.post("/totp/setup", response_model=TotpSetupRead)
async def totp_setup(user: CurrentUser, session: Session) -> TotpSetupRead:
    row = await service.totp_setup(session, user)
    return TotpSetupRead(
        secret=row.secret,
        otpauth_uri=totp.provisioning_uri(row.secret, user.email),
    )


@auth_router.post("/totp/confirm", status_code=204)
async def totp_confirm(data: TotpCodeRequest, user: CurrentUser, session: Session) -> None:
    await service.totp_confirm(session, user, data.code)


@auth_router.delete("/totp", status_code=204)
async def totp_disable(data: TotpCodeRequest, user: CurrentUser, session: Session) -> None:
    await service.totp_disable(session, user, data.code)


@auth_router.post("/logout", status_code=204)
async def logout(request: Request, session: Session, response: Response) -> None:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        await service.delete_session_by_token(session, token)
    response.delete_cookie(SESSION_COOKIE_NAME)


async def _me_read(session: AsyncSession, user: User) -> MeRead:
    """Spec 86 stage 3: flat shape — `global_role` + the global-scope
    `permissions` union top-level (the synthetic `workspaces` entry is gone).

    Spec 87: the union comes from `effective_permissions`, so instance-wide role
    grants show up here — otherwise the SPA would hide affordances the server
    would happily allow."""
    from radd.modules.teams import service as teams  # deferred: teams loads after auth

    admin = await authz.is_admin(session, user)
    role = InstanceRole.ADMIN if admin else InstanceRole.MEMBER
    return MeRead(
        manages_teams=await teams.stewards_any_team(session, user.id),
        id=user.id,
        email=user.email,
        name=user.name,
        instance_role=user.instance_role,
        global_role=role,
        permissions=sorted(await authz.effective_permissions(session, user)),
        avatar_color=user.avatar_color,
        avatar_emoji=user.avatar_emoji,
        timezone=user.timezone,
    )


@auth_router.get("/me", response_model=MeRead)
async def me(user: CurrentUser, session: Session) -> MeRead:
    return await _me_read(session, user)


@auth_router.patch("/me", response_model=MeRead)
async def update_me(data: ProfileUpdate, user: CurrentUser, session: Session) -> MeRead:
    """Self-service profile (spec 34): name, avatar color/emoji, timezone."""
    await service.update_profile(session, user, data)
    return await _me_read(session, user)


@auth_router.get("/me/preferences")
async def get_preferences(user: CurrentUser) -> dict[str, Any]:
    """The signed-in user's preferences dict (spec 94) — server-side, so it follows them across
    browsers. Any plugin/feature stashes small per-user prefs here (e.g. disabled contributions)."""
    return dict(user.preferences or {})


@auth_router.put("/me/preferences")
async def put_preferences(
    patch: dict[str, Any], user: CurrentUser, session: Session
) -> dict[str, Any]:
    """Merge `patch` into the user's preferences (shallow). Returns the full merged dict."""
    merged = {**(user.preferences or {}), **patch}
    user.preferences = merged
    await session.flush()
    return merged


@user_router.post("", response_model=UserRead, status_code=201)
async def create_user(data: UserCreate, session: Session, actor: CurrentUser) -> UserRead:
    await authz.require(session, actor, authz.Permission.USER_CREATE)
    return UserRead.model_validate(await service.create_user(session, data, actor_id=actor.id))


@user_router.get("/{user_id}/permissions", response_model=list[PermissionSourceRead])
async def user_permissions(
    user_id: uuid.UUID,
    session: Session,
    actor: CurrentUser,
    project_id: uuid.UUID | None = None,
    space_id: uuid.UUID | None = None,
) -> list[PermissionSourceRead]:
    """What this person can do here, and WHY (RADD-779; space scope RADD-809).

    The question the whole access-control epic started from — "why can this
    member delete cycles?" — previously needed a read of `authz.py`, a query
    against the database and a hand-computed union. It is answerable from one
    request now, and from the Users page that raised it.

    Gated on `user.manage`: it describes another account's authority, which is
    administrative even though every atom in it is already enforced elsewhere.
    """
    await authz.require(session, actor, authz.Permission.USER_MANAGE)
    if project_id is not None and space_id is not None:
        raise HTTPException(status_code=422, detail="inspect a project or a space, not both")
    target = await service.get_user(session, user_id)
    project = None
    if project_id is not None:
        from radd.modules.projects import service as projects_service

        project = await projects_service.get_project(session, project_id)
    sources = await authz.permission_sources(
        session, target, project=project, space_id=space_id
    )
    return [PermissionSourceRead.model_validate(s, from_attributes=True) for s in sources]


@user_router.get("/{user_id}/access", response_model=UserAccessRead)
async def user_resource_access(
    user_id: uuid.UUID, session: Session, actor: CurrentUser
) -> UserAccessRead:
    """The OTHER half of the inspector (RADD-809): spec-92 resource access —
    which grant rows reach this person, through what, at what scope — plus
    plain-count effective answers. `permission_sources` explains atoms; this
    explains the layer the atoms never see, which is exactly the half that
    produced RADD-808's hour of hunting."""
    await authz.require(session, actor, authz.Permission.USER_MANAGE)
    target = await service.get_user(session, user_id)

    from radd.modules.access import inspect as access_inspect
    from radd.modules.teams import service as teams_service
    from radd.modules.projects import service as projects_service

    team_ids = await teams_service.user_team_ids(session, target.id)
    role_ids = await authz.all_held_role_ids(session, target)
    teams_by_id = await teams_service.teams_by_ids(session, team_ids)
    roles_by_id = await roles_service.roles_by_ids(session, set(role_ids))
    resources = await access_inspect.subject_access(
        session,
        user_id=target.id,
        team_ids=team_ids,
        role_ids=role_ids,
        team_names={tid: team.name for tid, team in teams_by_id.items()},
        role_names={rid: role.name for rid, role in roles_by_id.items()},
    )

    readable = await authz.require_anywhere(session, target, authz.Permission.ITEM_READ)
    updatable = await authz.require_anywhere(session, target, authz.Permission.ITEM_UPDATE)
    total_projects = len(await projects_service.list_projects(session))
    readable_spaces: int | None = None
    total_spaces: int | None = None
    try:
        from radd.modules.pages import access as pages_access
        from radd.modules.pages.models import PageSpace
    except ImportError:
        pass
    else:
        from sqlalchemy import func as _func, select as _select

        readable_spaces = len(await pages_access.readable_spaces(session, target))
        total_spaces = (
            await session.scalar(_select(_func.count()).select_from(PageSpace))
        ) or 0

    return UserAccessRead(
        resources=[
            ResourceTypeAccessRead.model_validate(section, from_attributes=True)
            for section in resources
        ],
        summary=AccessSummaryRead(
            readable_projects=len(readable),
            updatable_projects=len(updatable),
            total_projects=total_projects,
            readable_spaces=readable_spaces,
            total_spaces=total_spaces,
        ),
    )


@user_router.get("/directory", response_model=list[UserDirectoryEntry])
async def list_user_directory(session: Session, actor: CurrentUser) -> list[UserDirectoryEntry]:
    """Who exists, for anyone with an account (RADD-769).

    Authentication IS the gate, and that is the finding rather than a shortcut.
    Every atom in the system describes what someone may do to an *entity* —
    there is none for "is a person here", because being able to sign in already
    answers it. Requiring one would mean minting an atom and backfilling it onto
    every builtin role so that it always held, which is a gate in name only.

    What makes that safe is the SHAPE, not a permission: `UserDirectoryEntry`
    carries no email, no instance role, no source, no sign-in history. The
    administrative directory keeps all of that behind `user.manage` below.

    **Declared above `/users/{user_id}` on purpose (RADD-761):** Starlette
    matches in declaration order, so a literal segment written after a `{uuid}`
    route is answered by that route — this would 422 about parsing "directory"
    as a UUID while appearing, correctly, in the schema and at /docs.
    `tests/test_route_shadowing.py` asserts it for the whole app.
    """
    return [UserDirectoryEntry.model_validate(u) for u in await service.list_users(session)]


@user_router.get("", response_model=list[UserRead])
async def list_users(
    session: Session,
    actor: CurrentUser,
    q: str | None = None,
    source: UserSource | None = None,
    active: bool | None = None,
) -> list[UserRead]:
    """User directory with spec-84 admin filters."""
    await authz.require(session, actor, authz.Permission.USER_MANAGE)
    users = await service.list_users(session, q=q, source=source, active=active)
    return [UserRead.model_validate(u) for u in users]


def _require_instance_admin(actor: User, action: str) -> None:
    if InstanceRole(actor.instance_role) is not InstanceRole.ADMIN:
        raise ForbiddenError(f"{action} requires an instance admin")


@user_router.get("/duplicates", response_model=list[DuplicateUserGroup])
async def list_duplicate_users(session: Session, actor: CurrentUser) -> list[DuplicateUserGroup]:
    """Candidate duplicate groups (spec 84): shared email local part or exact
    case-insensitive name. A heuristic feed for the merge UI — never auto-merges."""
    _require_instance_admin(actor, "duplicate detection")
    return [
        DuplicateUserGroup(kind=kind, key=key, users=[UserRead.model_validate(u) for u in users])
        for kind, key, users in await service.duplicate_user_groups(session)
    ]


@user_router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: uuid.UUID, data: UserAdminUpdate, session: Session, actor: CurrentUser
) -> UserRead:
    """User administration (spec 84 + 86): rename, activate/deactivate, and set
    instance_role (admin|member — THE role ladder now that the members endpoints
    are gone). Deactivation revokes sessions and blocks every login path;
    deactivating or demoting yourself is a 409.

    Spec 87 split the gate. Renaming and activating are governed by the
    `user.update` atom, so an instance-wide grant can delegate day-to-day user
    administration. Setting `instance_role` stays a hard instance-admin check —
    otherwise user.update would be a self-serve route to admin.
    """
    await authz.require(session, actor, authz.Permission.USER_UPDATE)
    if data.instance_role is not None:
        _require_instance_admin(actor, "changing a user's instance role")
    return UserRead.model_validate(await service.update_user_admin(session, user_id, data, actor))


@user_router.get("/{user_id}/content", response_model=UserContentSummary)
async def user_content(
    user_id: uuid.UUID, session: Session, actor: CurrentUser
) -> UserContentSummary:
    """What this account owns (spec 89) — the delete dialog shows it before asking
    who inherits, and it answers whether a successor is needed at all."""
    await authz.require(session, actor, authz.Permission.USER_MANAGE)
    await service.get_user(session, user_id)
    return UserContentSummary(**await service.user_content_summary(session, user_id))


_DELETE_DOC = (
    "HARD-delete a user (spec 89). Everything they authored — issues, comments, docs, views, "
    "dashboards, owned teams, attachments, approvals — is reassigned to `reassign_to`, which is "
    "REQUIRED when the account owns anything (409 otherwise; use GET /users/{id}/content to "
    "check first). Their WORKLOGS are deleted rather than moved, so nobody is credited with "
    "hours they did not work. Personal state (sessions, tokens, MFA, stars, memberships, "
    "shares) dies with the account. Deleting yourself is a 409. The row really goes — use "
    "PATCH /users/{id} {active:false} to merely revoke access, or POST /users/{id}/merge to "
    "keep a deactivated shell for audit."
)


@user_router.delete("/{user_id}", status_code=204, description=_DELETE_DOC)
async def delete_user(
    user_id: uuid.UUID,
    session: Session,
    actor: CurrentUser,
    reassign_to: uuid.UUID | None = None,
) -> None:
    await authz.require(session, actor, authz.Permission.USER_DELETE)
    await service.delete_user(session, user_id, reassign_to, actor=actor)


@user_router.post("/{user_id}/merge", response_model=UserRead)
async def merge_user(
    user_id: uuid.UUID, data: UserMergeRequest, session: Session, actor: CurrentUser
) -> UserRead:
    """Fold a duplicate identity (Jira import / AD import / seed) into another user:
    every reference repoints, the duplicate is revoked + deactivated. Instance
    admins only."""
    if InstanceRole(actor.instance_role) is not InstanceRole.ADMIN:
        raise ForbiddenError("user merge requires an instance admin")
    target = await service.merge_users(session, user_id, data.into_user_id, actor_id=actor.id)
    return UserRead.model_validate(target)


@token_router.post("", response_model=TokenCreated, status_code=201)
async def create_token(data: TokenCreate, session: Session, user: CurrentUser) -> TokenCreated:
    try:
        token, raw = await service.create_api_token(session, user, data)
    except ValueError as exc:  # an unknown atom in the scope
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return TokenCreated(
        token=raw,
        id=token.id,
        name=token.name,
        prefix_display=token.prefix_display,
        expires_at=token.expires_at,
        scopes=token.scopes,
    )


@token_router.get("", response_model=list[TokenRead])
async def list_tokens(session: Session, user: CurrentUser) -> list[TokenRead]:
    return [TokenRead.model_validate(t) for t in await service.list_api_tokens(session, user)]


@token_router.delete("/{token_id}", status_code=204)
async def delete_token(token_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    await service.delete_api_token(session, user, token_id)


# --- service accounts (spec 113) ---

service_account_router = APIRouter(prefix="/service-accounts", tags=["service accounts"])


async def _account_read(session: Session, account) -> ServiceAccountRead:
    read = ServiceAccountRead.model_validate(account)
    read.token_count = await service_accounts.token_count(session, account.id)
    return read


@service_account_router.post("", response_model=ServiceAccountRead, status_code=201)
async def create_service_account(
    data: ServiceAccountCreate, session: Session, user: CurrentUser
) -> ServiceAccountRead:
    await authz.require(session, user, authz.Permission.SERVICE_ACCOUNT_CREATE)
    account = await service_accounts.create_account(session, data, actor_id=user.id)
    return await _account_read(session, account)


@service_account_router.get("", response_model=list[ServiceAccountRead])
async def list_service_accounts(session: Session, user: CurrentUser) -> list[ServiceAccountRead]:
    await authz.require(session, user, authz.Permission.GLOBAL_MANAGE)
    return [await _account_read(session, a) for a in await service_accounts.list_accounts(session)]


@service_account_router.patch("/{account_id}", response_model=ServiceAccountRead)
async def update_service_account(
    account_id: uuid.UUID, data: ServiceAccountUpdate, session: Session, user: CurrentUser
) -> ServiceAccountRead:
    await authz.require(session, user, authz.Permission.SERVICE_ACCOUNT_UPDATE)
    account = await service_accounts.update_account(session, account_id, data, actor_id=user.id)
    return await _account_read(session, account)


@service_account_router.post("/{account_id}/keys", response_model=TokenCreated, status_code=201)
async def create_service_account_key(
    account_id: uuid.UUID, data: TokenCreate, session: Session, user: CurrentUser
) -> TokenCreated:
    """Mint a key for an account that cannot log in to mint its own. The scope is
    validated against the atom catalog here — an unknown atom is a 422, not a
    permission that silently never matches."""
    await authz.require(session, user, authz.Permission.SERVICE_ACCOUNT_UPDATE)
    try:
        token, raw = await service_accounts.create_key(session, account_id, data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return TokenCreated(
        token=raw,
        id=token.id,
        name=token.name,
        prefix_display=token.prefix_display,
        expires_at=token.expires_at,
        scopes=token.scopes,
    )


@service_account_router.get("/{account_id}/keys", response_model=list[TokenRead])
async def list_service_account_keys(
    account_id: uuid.UUID, session: Session, user: CurrentUser
) -> list[TokenRead]:
    await authz.require(session, user, authz.Permission.GLOBAL_MANAGE)
    return [TokenRead.model_validate(t) for t in await service_accounts.list_keys(session, account_id)]


@service_account_router.delete("/{account_id}/keys/{token_id}", status_code=204)
async def revoke_service_account_key(
    account_id: uuid.UUID, token_id: uuid.UUID, session: Session, user: CurrentUser
) -> None:
    await authz.require(session, user, authz.Permission.SERVICE_ACCOUNT_UPDATE)
    await service_accounts.revoke_key(session, account_id, token_id)
