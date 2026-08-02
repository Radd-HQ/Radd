import asyncio
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import get_session
from radd.exceptions import ConflictError, ForbiddenError, RaddError
from radd.modules.auth import authz, service as auth_service
from radd.modules.auth.deps import CurrentUser
from radd.modules.auth.models import User
from radd.modules.auth.types import SESSION_COOKIE_NAME, InstanceRole
from radd.modules.teams import service as teams_service

from . import groups, groupsync, service, state, userimport, usersync
from .models import DirectorySyncState
from .types import ImportResolution, ImportStatus, LdapEntity, SyncKind
from .schemas import (
    DirectoryGroupRead,
    DirectorySyncResult,
    DirectorySyncStateRead,
    DirectorySyncStatusRead,
    DirectoryUserImportRequest,
    DirectoryUserImportResult,
    DirectoryUserRead,
    ExistingMatchRead,
    GroupImportRequest,
    GroupImportResult,
    ImportCandidateRead,
    LdapLoginRequest,
    UserSyncResultRead,
)

router = APIRouter(prefix="/auth/ldap", tags=["sso"])
# Spec 84: directory administration (group/user pickers + imports) — instance
# admin + a configured bind account (409 without one).
admin_router = APIRouter(prefix="/ldap", tags=["ldap"])
# Spec 84 §1c: on-demand team reconcile (team.manage).
team_sync_router = APIRouter(prefix="/teams", tags=["teams"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.post("/login", status_code=204)
async def ldap_login(data: LdapLoginRequest, session: Session, response: Response) -> None:
    """Directory sign-in (spec 42): direct bind as <username>@<domain>, then
    provisioning + role sync and an ordinary session cookie — the same shape
    as the local /auth/login. Spec 84: the same connection also answers the
    user's transitive membership in every linked team's group, so directory
    team seats join/leave on login without a service account."""
    linked = await teams_service.linked_teams(session)
    directory_user = await service.authenticate(
        data.username.strip(),
        data.password,
        tuple(team.directory_group_dn for team in linked if team.directory_group_dn),
    )
    user = await service.provision(session, directory_user)
    await groupsync.sync_login_membership(session, user, linked, directory_user.team_group_dns)
    token = await auth_service.create_session(session, user)
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
    )


def _require_instance_admin(actor: User) -> None:
    if InstanceRole(actor.instance_role) is not InstanceRole.ADMIN:
        raise ForbiddenError("directory administration requires an instance admin")


@admin_router.get("/groups", response_model=list[DirectoryGroupRead])
async def search_directory_groups(
    session: Session, actor: CurrentUser, q: str = ""
) -> list[DirectoryGroupRead]:
    """Paged AD group search for the link/import pickers (spec 84; spec 85: the
    base DN resolves through the settings cascade)."""
    _require_instance_admin(actor)
    groups.require_bind_account()
    return [
        DirectoryGroupRead(
            cn=g.cn, dn=g.dn, description=g.description, member_count=g.member_count
        )
        for g in await groups.search_groups(session, q)
    ]


@admin_router.post("/groups/import", response_model=list[GroupImportResult])
async def import_directory_groups(
    data: GroupImportRequest, session: Session, actor: CurrentUser
) -> list[GroupImportResult]:
    """Spec 84 §2: per group create-or-link a team, resolve transitive members,
    optionally provision unknown users, add directory-source memberships."""
    _require_instance_admin(actor)
    groups.require_bind_account()
    outcomes = await groupsync.import_groups(
        session, data.group_dns, data.provision_members, actor_id=actor.id
    )
    return [
        GroupImportResult(
            group_dn=o.group_dn,
            cn=o.cn,
            team_id=o.team_id,
            created=o.created,
            members_added=o.members_added,
            users_provisioned=o.users_provisioned,
            error=o.error,
        )
        for o in outcomes
    ]


@admin_router.get("/directory-users", response_model=list[DirectoryUserRead])
async def search_ldap_directory_users(
    session: Session, actor: CurrentUser, q: str = ""
) -> list[DirectoryUserRead]:
    """Directory user search for the import-from-AD picker (spec 84; the
    spec-49 enumeration narrowed by q over cn/sAMAccountName/mail; spec 85: the
    base DN resolves through the settings cascade)."""
    _require_instance_admin(actor)
    groups.require_bind_account()
    base = await service.resolved_user_base(session)
    skip_disabled = await service.resolved_exclude_disabled(session)
    users = await asyncio.to_thread(service.search_directory_users, q, base, skip_disabled)
    return [DirectoryUserRead(username=u.username, email=u.email, name=u.name) for u in users]


async def _selected_directory_users(session: AsyncSession, emails: list[str]) -> tuple[dict, list[str]]:
    """The chosen directory users by lowercased email, plus the emails the
    enumeration no longer returns (reported, never guessed at)."""
    base = await service.resolved_user_base(session)
    found = {
        u.email: u
        for u in await asyncio.to_thread(
            service.search_directory_users, "", base, await service.resolved_exclude_disabled(session)
        )
    }
    wanted = list(dict.fromkeys(e.strip().lower() for e in emails if e.strip()))
    return {email: found[email] for email in wanted if email in found}, [
        email for email in wanted if email not in found
    ]


_PREVIEW_DOC = (
    "Dry run of an AD user import (spec 88): classifies each selected directory user against "
    "the accounts that already exist — `new`, `linked` (the exact email is already here), or "
    "`conflict` (this looks like an existing person under a DIFFERENT email, matched on the AD "
    "username vs. an email local part, or an identical display name). Radd has no username "
    "column — identity is the email — which is why a username can only be compared that way. "
    "Nothing is written; the returned `suggested` resolution is a hint, and the admin's choices "
    "come back on the import call. Name matches especially are a heuristic, never auto-applied."
)


@admin_router.post(
    "/directory-users/import/preview",
    response_model=list[ImportCandidateRead],
    description=_PREVIEW_DOC,
)
async def preview_ldap_directory_user_import(
    data: DirectoryUserImportRequest, session: Session, actor: CurrentUser
) -> list[ImportCandidateRead]:
    _require_instance_admin(actor)
    groups.require_bind_account()
    selected, missing = await _selected_directory_users(session, data.emails)
    candidates = userimport.plan_user_import(
        selected.values(), await auth_service.list_users(session)
    )
    reads = [
        ImportCandidateRead(
            username=c.username,
            email=c.email,
            name=c.name,
            status=c.status,
            matches=[ExistingMatchRead(**vars(m)) for m in c.matches],
            suggested=c.suggested,
        )
        for c in candidates
    ]
    # Surface a selection the directory no longer knows about rather than
    # dropping it silently — the picker's data can be minutes stale.
    reads.extend(
        ImportCandidateRead(
            username="",
            email=email,
            name="",
            status=ImportStatus.NEW,
            matches=[],
            suggested=ImportResolution.SKIP,
        )
        for email in missing
    )
    return reads


@admin_router.post("/directory-users/import", response_model=list[DirectoryUserImportResult])
async def import_ldap_directory_users(
    data: DirectoryUserImportRequest, session: Session, actor: CurrentUser
) -> list[DirectoryUserImportResult]:
    """Provision the selected directory users ahead of their first login
    (spec 84; the spec-42 path: SSO-only account, source=ldap — a new active
    user holds the global member floor).

    Spec 88: each entry may carry a `resolution` from the preview above —
    `overwrite` gives an existing account AD's email/name (keeping its id, so the
    person's history follows), `merge` folds a look-alike into the AD-identified
    account, `skip` does nothing. An email with no resolution keeps the pre-88
    behavior: create-or-link, existing accounts untouched.
    """
    _require_instance_admin(actor)
    groups.require_bind_account()
    selected, missing = await _selected_directory_users(session, data.emails)
    chosen = {
        entry.email.strip().lower(): entry for entry in data.resolutions
    }
    results = [
        DirectoryUserImportResult(
            email=email,
            user_id=None,
            created=False,
            resolution=ImportResolution.SKIP,
            error="not found in the directory",
        )
        for email in missing
    ]
    for email, directory_user in selected.items():
        entry = chosen.get(email)
        resolution = entry.resolution if entry else ImportResolution.CREATE
        try:
            before = (
                await auth_service.get_user(session, entry.target_user_id)
                if entry and entry.target_user_id and resolution is ImportResolution.MERGE
                else None
            )
            user, created = await userimport.apply_resolution(
                session,
                directory_user,
                resolution,
                entry.target_user_id if entry else None,
                actor_id=actor.id,
            )
            results.append(
                DirectoryUserImportResult(
                    email=email,
                    user_id=user.id if user else None,
                    created=created,
                    resolution=resolution,
                    merged_user_id=before.id if before else None,
                )
            )
        except RaddError as exc:
            # One bad decision (an email already taken, a nonsense merge) must not
            # abandon the rest of the batch — it is reported on its own row.
            results.append(
                DirectoryUserImportResult(
                    email=email,
                    user_id=None,
                    created=False,
                    resolution=resolution,
                    error=str(exc),
                )
            )
    return results


def _state_read(row: DirectorySyncState | None) -> DirectorySyncStateRead | None:
    if row is None:
        return None
    return DirectorySyncStateRead(
        kind=row.kind, last_run_at=row.last_run_at, last_result=row.last_result
    )


@admin_router.get("/sync-status", response_model=DirectorySyncStatusRead)
async def directory_sync_status(session: Session, actor: CurrentUser) -> DirectorySyncStatusRead:
    """Both `directory_sync_state` rows (spec 85) — instance admin. Readable
    without a bind account (a de-configured deploy can still see history)."""
    _require_instance_admin(actor)
    states = await state.all_states(session)
    return DirectorySyncStatusRead(
        user_sync=_state_read(states.get(SyncKind.USER_SYNC)),
        group_sync=_state_read(states.get(SyncKind.GROUP_SYNC)),
    )


@admin_router.post("/sync/users", response_model=UserSyncResultRead)
async def run_directory_user_sync(session: Session, actor: CurrentUser) -> UserSyncResultRead:
    """The spec-85 user-sync pass, on demand ("Sync now") — instance admin,
    409 without a bind account. Same code path as the ldap-usersync loop; the
    directory search runs in a thread inside."""
    _require_instance_admin(actor)
    groups.require_bind_account()
    result = await usersync.run_user_sync(session, actor_id=actor.id)
    return UserSyncResultRead(**result.payload())


@team_sync_router.post("/{team_id}/directory-sync", response_model=DirectorySyncResult)
async def directory_sync_team(
    team_id: uuid.UUID, session: Session, actor: CurrentUser
) -> DirectorySyncResult:
    """On-demand reconcile of one linked team (spec 84 §1c) — team.manage;
    409 when no bind account or the team isn't linked."""
    team = await teams_service.get_team(session, team_id)
    await authz.require(
        session, actor, authz.Permission.TEAM_UPDATE
    )
    groups.require_bind_account()
    if not team.directory_group_dn:
        raise ConflictError(LdapEntity.LDAP, reason="team is not linked to a directory group")
    try:
        added, removed = await groupsync.reconcile_team(session, team, actor_id=actor.id)
    except groupsync.StaleDirectoryGroup as exc:
        # Spec 87: the group is gone from AD. The team was left untouched — say so
        # (409) instead of reporting a successful sync that removed everybody.
        raise ConflictError(LdapEntity.LDAP, reason=str(exc)) from exc
    return DirectorySyncResult(added=added, removed=removed)
