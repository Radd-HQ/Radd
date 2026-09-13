import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.apitypes import TOTAL_COUNT_HEADER
from radd.choices import ChoiceRead
from radd.db import get_session
from radd.exceptions import ForbiddenError, UnauthorizedError
from radd.kernel import registries

from . import account_directory, authz, grants, roles as roles_service, service, service_accounts, totp
from . import principals
from .deps import Actor, CurrentUser
from .models import User
from .principals import require_account_session
from .throttle import check_login_attempt
from .schemas import (
    CarrierGrantRead,
    MembershipRead,
    AccessSummaryRead,
    ServiceAccountCreate,
    ServiceAccountRead,
    ServiceKeySummaryRead,
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
    TotpRecoveryCodesRead,
    TotpLoginRequest,
    TotpSetupRead,
    TotpStatusRead,
    UserAccessRead,
    UserAdminUpdate,
    PermissionSourceRead,
    ViewAsRead,
    ViewAsStart,
    SuccessorCheck,
    SuccessorGap,
    UserContentSummary,
    UserCreate,
    UserDirectoryEntry,
    UserMergeRequest,
    UserRead,
)
from .types import (
    NON_PERSON_SOURCES,
    RELATION_ANY,
    SESSION_COOKIE_NAME,
    GrantScopeKind,
    InstanceRole,
    UserSource,
    relations_held,
)
from radd.modules.access.types import GrantSubject

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
async def login(data: LoginRequest, session: Session, response: Response, request: Request) -> None:
    check_login_attempt(request, data.email)
    user = await service.authenticate(session, data.email, data.password)
    if await service.totp_required(session, user):
        # No cookie yet — the client repeats via /login/totp with a code.
        raise UnauthorizedError(TOTP_REQUIRED)
    _set_session_cookie(response, await service.create_session(session, user))


@auth_router.post("/login/totp", status_code=204)
async def login_totp(data: TotpLoginRequest, session: Session, response: Response, request: Request) -> None:
    """Second MFA step (spec 48): stateless — password re-verified with the code."""
    check_login_attempt(request, data.email)
    user = await service.authenticate_with_totp(session, data.email, data.password, data.code)
    _set_session_cookie(response, await service.create_session(session, user))


@auth_router.get("/totp", response_model=TotpStatusRead)
async def totp_status(user: CurrentUser, session: Session) -> TotpStatusRead:
    row = await service.totp_row(session, user.id)
    return TotpStatusRead(
        enabled=row is not None and row.confirmed_at is not None,
        pending=row is not None and row.confirmed_at is None,
        recovery_codes_remaining=await service.recovery_codes_remaining(session, user.id),
    )


@auth_router.post("/totp/setup", response_model=TotpSetupRead)
async def totp_setup(user: CurrentUser, session: Session) -> TotpSetupRead:
    row = await service.totp_setup(session, user)
    return TotpSetupRead(
        secret=row.secret,
        otpauth_uri=totp.provisioning_uri(row.secret, user.email),
    )


@auth_router.post("/totp/confirm", response_model=TotpRecoveryCodesRead)
async def totp_confirm(
    data: TotpCodeRequest, user: CurrentUser, session: Session
) -> TotpRecoveryCodesRead:
    """Confirms enrollment and returns the recovery codes — shown once, never
    retrievable again (RADD-677)."""
    return TotpRecoveryCodesRead(
        recovery_codes=await service.totp_confirm(session, user, data.code)
    )


@auth_router.post("/totp/recovery-codes", response_model=TotpRecoveryCodesRead)
async def totp_regenerate_recovery_codes(
    data: TotpCodeRequest, user: CurrentUser, session: Session
) -> TotpRecoveryCodesRead:
    """A fresh batch (invalidates every old code), gated on a live TOTP code."""
    return TotpRecoveryCodesRead(
        recovery_codes=await service.regenerate_recovery_codes(session, user, data.code)
    )


@auth_router.delete("/totp", status_code=204)
async def totp_disable(data: TotpCodeRequest, user: CurrentUser, session: Session) -> None:
    await service.totp_disable(session, user, data.code)


@auth_router.post("/logout", status_code=204)
async def logout(request: Request, session: Session, response: Response) -> None:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        await service.delete_session_by_token(session, token)
    response.delete_cookie(SESSION_COOKIE_NAME)


async def _nav_facts(session: AsyncSession, user: User) -> dict[str, bool]:
    """RADD-843: the area-visibility facts the client cannot derive from lists it
    already loads — RADD-892: whichever ones are REGISTERED.

    auth used to import timelogging and forms to ask them, which inverted the
    load order: two optional features that load after auth, named by the module
    they load under. Now each contributes a `NavFactSpec` and this reads the
    registry — at request time, since a plugin may be enabled after boot. A
    module that is not loaded leaves its key absent, which the SPA reads as
    visible, exactly as the old feature-detection did."""
    return {
        spec.key: await spec.resolve(session, user)
        for spec in registries.nav_facts.values()
    }


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
        nav=await _nav_facts(session, user),
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
async def me(request: Request, user: Actor, session: Session) -> MeRead:
    """Who is here. Spec 121: answers 200 for an unauthenticated request too —
    `anonymous=True`, the Anyone principal's id, and its (grant-only) global
    permissions — so the SPA can render the shell for a visitor instead of
    bouncing every public link to the login page."""
    payload = await _me_read(session, user)
    payload.anonymous = principals.is_anonymous(user)
    # RADD-836 U1: while previewing, the payload describes the TARGET (that is
    # the point); the banner needs to know who is really here.
    real = getattr(request.state, "view_as_real", None)
    if real is not None:
        payload.view_as = ViewAsRead(real_id=real.id, real_name=real.name)
    return payload


@auth_router.post("/view-as", status_code=204)
async def start_view_as(
    request: Request, data: ViewAsStart, session: Session, actor: CurrentUser
) -> None:
    """Begin a read-only preview as another user (RADD-836 U1). Instance-admin
    only, session-cookie only (a PAT has no session to carry the preview), and
    audited on entry. While previewing, deps.py refuses every write except
    exiting and logging out — enforcement is the resolution seam, not hidden
    buttons."""
    if not await authz.is_admin(session, actor):
        raise ForbiddenError("only an instance admin may preview as another user")
    token = request.cookies.get(SESSION_COOKIE_NAME)
    row = await service.session_row_for_token(session, token) if token else None
    if row is None:
        raise HTTPException(status_code=409, detail="view-as needs a browser session")
    await service.start_view_as(session, admin=actor, row=row, target_id=data.user_id)


@auth_router.delete("/view-as", status_code=204)
async def end_view_as(request: Request, session: Session, actor: CurrentUser) -> None:
    """Exit the preview (exempt from the read-only guard) — audited."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    row = await service.session_row_for_token(session, token) if token else None
    if row is None:
        return
    real = getattr(request.state, "view_as_real", None) or actor
    await service.end_view_as(session, admin=real, row=row)


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


async def _carrier_grants(
    session: AsyncSession,
    *,
    team_id: uuid.UUID | None = None,
    group_id: uuid.UUID | None = None,
) -> list[CarrierGrantRead]:
    """What a team or group CONFERS on its members (RADD-933).

    Returns an empty list rather than being omitted when the carrier grants
    nothing, because "you are on this team and it gives you nothing" is a real
    and common answer — and it is the row that explains the change when someone
    later grants a role to that team.
    """
    from radd.modules.projects import service as projects_service

    rows = await grants.grants_for_subject(session, team_id=team_id, group_id=group_id)
    if not rows:
        return []
    role_names = await roles_service.roles_by_ids(session, {row.role_id for row in rows})
    project_keys = await projects_service.project_keys(
        session, {row.project_id for row in rows if row.project_id is not None}
    )
    space_names = await authz.scope_labels(
        session, GrantScopeKind.SPACE, {row.space_id for row in rows if row.space_id is not None}
    )
    out: list[CarrierGrantRead] = []
    for row in rows:
        if row.project_id is not None:
            scope, label = "project", project_keys.get(row.project_id)
        elif row.space_id is not None:
            scope, label = "space", space_names.get(row.space_id)
        else:
            scope, label = "global", None
        role = role_names.get(row.role_id)
        out.append(
            CarrierGrantRead(
                role_name=role.name if role else "?", scope=scope, scope_label=label
            )
        )
    return out


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
    from radd.modules.groups import service as groups_service
    from radd.modules.teams import service as teams_service
    from radd.modules.projects import service as projects_service

    team_ids = await teams_service.user_team_ids(session, target.id)
    group_ids = await groups_service.user_group_ids(session, target.id)
    role_ids = await authz.all_held_role_ids(session, target)
    teams_by_id = await teams_service.teams_by_ids(session, team_ids)
    groups_by_id = await groups_service.groups_by_ids(session, group_ids)
    roles_by_id = await roles_service.roles_by_ids(session, set(role_ids))
    resources = await access_inspect.subject_access(
        session,
        user_id=target.id,
        team_ids=team_ids,
        role_ids=role_ids,
        group_ids=group_ids,
        team_names={tid: team.name for tid, team in teams_by_id.items()},
        role_names={rid: role.name for rid, role in roles_by_id.items()},
        group_names={gid: group.name for gid, group in groups_by_id.items()},
    )

    # RADD-933: the two counts are UNQUALIFIED vs qualified-only. `holds_base`
    # (what require_anywhere gates on) is right for a gate and wrong for a
    # summary — see AccessSummaryRead.
    def _split_reach(
        held: dict[uuid.UUID, frozenset[str]], atom: str
    ) -> tuple[int, int]:
        full = qualified = 0
        for permissions in held.values():
            relations = relations_held(permissions, atom)
            if RELATION_ANY in relations:
                full += 1
            elif relations:
                qualified += 1
        return full, qualified

    readable_full, readable_own = _split_reach(
        await authz.require_anywhere(session, target, authz.Permission.ITEM_READ),
        authz.Permission.ITEM_READ,
    )
    updatable_full, updatable_own = _split_reach(
        await authz.require_anywhere(session, target, authz.Permission.ITEM_UPDATE),
        authz.Permission.ITEM_UPDATE,
    )
    total_projects = len(await projects_service.list_projects(session))

    # The carriers between "granted to" and "held by" (RADD-933). team_ids and
    # group_ids are already resolved above for the resource attribution; this
    # endpoint used to compute them and return neither, so the Users page could
    # not say which teams a person was on — let alone what those teams conferred.
    memberships: list[MembershipRead] = []
    for team_id, team in sorted(teams_by_id.items(), key=lambda kv: kv[1].name):
        memberships.append(
            MembershipRead(
                kind=GrantSubject.TEAM.value,
                id=team_id,
                name=team.name,
                confers=await _carrier_grants(session, team_id=team_id),
            )
        )
    for group_id, group in sorted(groups_by_id.items(), key=lambda kv: kv[1].name):
        path = await groups_service.membership_path(session, target.id, group_id)
        memberships.append(
            MembershipRead(
                kind=GrantSubject.GROUP.value,
                id=group_id,
                name=group.name,
                path=[g.name for g in path] if path else None,
                confers=await _carrier_grants(session, group_id=group_id),
            )
        )
    # RADD-892: how much of a SCOPE KIND the actor reaches is the scope owner's
    # answer — spaces carry per-space ACLs auth cannot compute. Absent kind (or a
    # kind that cannot answer, like project, whose readability is an atom
    # question auth answers above) leaves the counts null.
    readable_spaces: int | None = None
    total_spaces: int | None = None
    space_scope = registries.grant_scopes.get(GrantScopeKind.SPACE)
    if space_scope is not None and space_scope.reach is not None:
        readable_spaces, total_spaces = await space_scope.reach(session, target)

    return UserAccessRead(
        resources=[
            ResourceTypeAccessRead.model_validate(section, from_attributes=True)
            for section in resources
        ],
        summary=AccessSummaryRead(
            readable_projects=readable_full,
            own_readable_projects=readable_own,
            updatable_projects=updatable_full,
            own_updatable_projects=updatable_own,
            total_projects=total_projects,
            readable_spaces=readable_spaces,
            total_spaces=total_spaces,
        ),
        memberships=memberships,
    )


@user_router.get("/directory/options", response_model=list[ChoiceRead])
async def person_name_choices(
    response: Response, session: Session, user: CurrentUser,
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    value: Annotated[str | None, Query(max_length=200)] = None,
) -> list[ChoiceRead]:
    from . import name_options
    rows, total = await name_options.list_options(session, q=q, limit=limit, offset=offset, value=value)
    response.headers[TOTAL_COUNT_HEADER] = str(total)
    return rows


@user_router.get("/directory", response_model=list[UserDirectoryEntry])
async def list_user_directory(
    response: Response,
    session: Session,
    actor: CurrentUser,
    q: str | None = None,
    project_id: uuid.UUID | None = None,
    include_requesters: Annotated[
        bool,
        Query(
            description=(
                "Include UserSource.EMAIL accounts (mail-provisioned requesters), "
                "excluded by default (RADD-1034)."
            )
        ),
    ] = False,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[UserDirectoryEntry]:
    """Who exists, for anyone with an account (RADD-769).

    Authentication IS the gate, and that is the finding rather than a shortcut.
    Every atom in the system describes what someone may do to an *entity* —
    there is none for "is a person here", because being able to sign in already
    answers it. Requiring one would mean minting an atom and backfilling it onto
    every builtin role so that it always held, which is a gate in name only.

    What makes that safe is the SHAPE, not a permission: `UserDirectoryEntry`
    carries no email, no instance role, no sign-in history. The administrative
    directory keeps all of that behind `user.manage` below.

    **`UserSource.EMAIL` accounts are excluded by default (RADD-1034).**
    `mailintake._sender_user` provisions one of these, active, for every
    unrecognized sender — so with no filter, one forged message made
    "Stranger <stranger@evil.example>" pickable by every authenticated user,
    forever (the shape guard above never covered this: it protects what a row
    exposes, not which rows are IN the list). Pass `include_requesters=true`
    for the surfaces that mean to offer them — the reporter picker on a
    mail-born ticket is the one today — and those rows carry `external=True`
    so the SPA can label them rather than hardcoding the `email` sentinel.
    Precedent for the same exclusion pair: `preflight.py`'s Baseline report,
    which also drops `UserSource.SERVICE`. Service accounts are NOT excluded
    here — unlike a stranger's email, they're deliberately created by an admin
    (spec 113), and `UserDirectoryEntry`'s own docstring is explicit that
    omitting them would leave page/comment bylines unresolvable.

    **Declared above `/users/{user_id}` on purpose (RADD-761):** Starlette
    matches in declaration order, so a literal segment written after a `{uuid}`
    route is answered by that route — this would 422 about parsing "directory"
    as a UUID while appearing, correctly, in the schema and at /docs.
    `tests/test_route_shadowing.py` asserts it for the whole app.
    """
    # Spec 121: the principal rows are never a person to pick, whatever is asked.
    sources_excluded = [UserSource.PRINCIPAL] if include_requesters else list(NON_PERSON_SOURCES)
    rows = await service.list_users(
        session, q=q, limit=limit, offset=offset, sources_excluded=sources_excluded
    )
    if limit is not None:
        response.headers[TOTAL_COUNT_HEADER] = str(
            await service.count_users(session, q=q, sources_excluded=sources_excluded)
        )
    entries = [UserDirectoryEntry.model_validate(u) for u in rows]
    for entry in entries:
        entry.external = entry.source == UserSource.EMAIL.value

    # RADD-938: `project_id` annotates each row with whether that person can
    # actually reach the project, for the controls that attach someone TO work
    # — assignee, participants, add-team. Without it the pickers offered every
    # account with no hint, so you could assign an issue to someone who would
    # never find it and learn about it days later.
    #
    # Annotated, never filtered. Hiding a colleague gives no reason and reads as
    # a bug; and under RADD-937 adding a no-access person as a participant is
    # exactly what makes the project visible to them, so the pick must stay
    # possible. The SPA groups and labels.
    #
    # Resolved as a SET once — asking `effective_permissions` per row would be
    # one resolution per account in the directory.
    #
    # Gated on the CALLER's own read of that project. Without this, any
    # authenticated account could ask "who has access to <project I cannot
    # see>?" and enumerate its membership — the directory is deliberately open
    # to everyone (RADD-769), so an ungated annotation would have widened it
    # from "who exists" to "who is on what". Silently unannotated rather than a
    # 403: `has_access=None` already means "not asked", and a picker that cannot
    # ask still works.
    if project_id is not None:
        visible = await authz.visible_projects(session, actor)
        if project_id in visible:
            entitled = await grants.users_entitled_to_project(session, project_id)
            for entry in entries:
                entry.has_access = entry.id in entitled
    return entries


@user_router.get("/options", response_model=list[ChoiceRead])
async def option_choices(
    response: Response, session: Session, user: CurrentUser,
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    value: Annotated[str | None, Query(max_length=320)] = None,
) -> list[ChoiceRead]:
    rows, total = await service.list_options(session, user, q=q, limit=limit, offset=offset, value=value)
    response.headers[TOTAL_COUNT_HEADER] = str(total)
    return rows


@user_router.get("", response_model=list[UserRead])
async def list_users(
    response: Response,
    session: Session,
    actor: CurrentUser,
    q: str | None = None,
    source: UserSource | None = None,
    active: bool | None = None,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[UserRead]:
    """User directory with spec-84 admin filters; limit/offset page (RADD-884)."""
    await authz.require(session, actor, authz.Permission.USER_MANAGE)
    users = await service.list_users(
        session, q=q, source=source, active=active, limit=limit, offset=offset
    )
    if limit is not None:
        response.headers[TOTAL_COUNT_HEADER] = str(
            await service.count_users(session, q=q, source=source, active=active)
        )
    return [UserRead.model_validate(u) for u in users]


def _require_instance_admin(actor: User, action: str) -> None:
    if not authz.is_instance_admin(actor):
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


@user_router.get("/{user_id}/successor-check", response_model=SuccessorCheck)
async def successor_check(
    user_id: uuid.UUID, candidate_id: uuid.UUID, session: Session, actor: CurrentUser
) -> SuccessorCheck:
    """RADD-784: would `candidate_id` be a viable successor for deleting this
    account? Access never transfers on delete, so the candidate must already
    hold at least what the account holds — the gaps name what is missing, per
    scope. The delete itself enforces the same check; this is the dialog's
    preview."""
    await authz.require(session, actor, authz.Permission.USER_MANAGE)
    user = await service.get_user(session, user_id)
    candidate = await service.get_user(session, candidate_id)
    gaps = await service.successor_viability(session, user, candidate)
    return SuccessorCheck(viable=not gaps, gaps=[SuccessorGap(**gap) for gap in gaps])


_DELETE_DOC = (
    "HARD-delete a user (spec 89). Everything they authored — issues, comments, docs, views, "
    "dashboards, attachments, approvals — is reassigned to `reassign_to`, which is "
    "REQUIRED when the account owns anything (409 otherwise; use GET /users/{id}/content to "
    "check first). Their WORKLOGS are deleted rather than moved, so nobody is credited with "
    "hours they did not work. ACCESS dies with the account (RADD-784): project and team "
    "memberships, role grants, delegation and shares are never inherited — and the successor "
    "must already hold at least the account's effective permissions, or the delete is refused "
    "naming what is missing (GET /users/{id}/successor-check?candidate_id= previews this). "
    "Owned teams go ownerless rather than transferring. Personal state (sessions, tokens, "
    "MFA, stars, watches, inbox) dies with the account. Deleting yourself is a 409. The row "
    "really goes — use PATCH /users/{id} {active:false} to merely revoke access, or POST "
    "/users/{id}/merge to keep a deactivated shell for audit."
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
    if not authz.is_instance_admin(actor):
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
async def list_service_accounts(
    response: Response, session: Session, user: CurrentUser,
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ServiceAccountRead]:
    await authz.require(session, user, authz.Permission.GLOBAL_MANAGE)
    if limit is not None:
        response.headers[TOTAL_COUNT_HEADER] = str(await account_directory.account_total(session, q))
    return await account_directory.accounts(session, q=q, limit=limit, offset=offset)


@service_account_router.get("/{account_id}", response_model=ServiceAccountRead)
async def get_service_account(account_id: uuid.UUID, session: Session, user: CurrentUser):
    await authz.require(session, user, authz.Permission.GLOBAL_MANAGE)
    return await account_directory.by_id(session, account_id)


@service_account_router.get("/{account_id}/keys/directory", response_model=list[ServiceKeySummaryRead])
async def service_key_directory(
    account_id: uuid.UUID, response: Response, session: Session, user: CurrentUser,
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    await authz.require(session, user, authz.Permission.GLOBAL_MANAGE)
    rows, total = await account_directory.keys(session, account_id, q=q, limit=limit, offset=offset)
    response.headers[TOTAL_COUNT_HEADER] = str(total)
    return rows


@service_account_router.patch("/{account_id}", response_model=ServiceAccountRead)
async def update_service_account(
    account_id: uuid.UUID, data: ServiceAccountUpdate, session: Session, user: CurrentUser
) -> ServiceAccountRead:
    """Rename/deactivate. No SPA caller today — DELIBERATELY kept (RADD-893):
    this is the only surface that can deactivate a compromised service account,
    the same keep-reason as plugin uninstall."""
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
    require_account_session(user)
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
