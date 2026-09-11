"""Users CRUD + TOTP/MFA — and the facade for the rest of `auth`'s service
layer (RADD-902).

This file used to hold everything: users, sessions + view-as, API tokens, and
the user-merge/hard-delete raw-SQL repoint block, in that order, ~1100 lines.
It's now split along those same markers into sibling modules — `sessions +
view-as` -> `service_sessions.py`, `API tokens` -> `service_tokens.py`, `user
merge + delete` -> `lifecycle.py` — each re-exported here under its original
name, so `from radd.modules.auth import service` + `service.create_session(...)`
(or any direct `from radd.modules.auth.service import X`) is unaffected.

Users CRUD and TOTP/MFA stay here: neither was called out as its own seam, and
together with `authenticate`/`update_profile` they're the part of this module
that isn't about a login artifact (session, token) or the merge/delete
lifecycle.
"""

import time
import uuid
from collections.abc import Iterable

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import ilike_term
from radd.exceptions import ConflictError, NotFoundError, UnauthorizedError
from radd.modules.events import service as events

from . import security, totp
from .lifecycle import (
    _CONTENT_COUNTS as _CONTENT_COUNTS,
    _DELETE_WITH_ACCOUNT as _DELETE_WITH_ACCOUNT,
    _MERGE_DEDUPE as _MERGE_DEDUPE,
    _MERGE_PURGE as _MERGE_PURGE,
    _MERGE_REPOINT as _MERGE_REPOINT,
    _dedupe_sql as _dedupe_sql,
    _permission_gaps as _permission_gaps,
    _repoint_user_access_grants as _repoint_user_access_grants,
    delete_user as delete_user,
    ensure_deletable as ensure_deletable,
    ensure_imported_user as ensure_imported_user,
    merge_users as merge_users,
    successor_viability as successor_viability,
    user_content_summary as user_content_summary,
)
from .models import TotpRecoveryCode, User, UserSession, UserTotp
from .options import list_options as list_options
from .schemas import ProfileUpdate, UserAdminUpdate, UserCreate
from .service_sessions import (
    create_session as create_session,
    delete_session_by_token as delete_session_by_token,
    end_view_as as end_view_as,
    resolve_session_users as resolve_session_users,
    session_row_for_token as session_row_for_token,
    start_view_as as start_view_as,
    user_for_session_token as user_for_session_token,
)
from .service_tokens import (
    _naive_utc as _naive_utc,
    create_api_token as create_api_token,
    delete_api_token as delete_api_token,
    list_api_tokens as list_api_tokens,
    user_for_api_token as user_for_api_token,
)
from .throttle import check_login_attempt as check_login_attempt
from .types import (
    AuthEntity,
    AuthEvent,
    DuplicateKind,
    InstanceRole,
    UserChange,
    UserSource,
)

# Uniform for unknown email / wrong password / inactive user — reveals nothing.
BAD_CREDENTIALS = "invalid email or password"


# --- users ---


async def create_user(
    session: AsyncSession, data: UserCreate, actor_id: uuid.UUID | None = None
) -> User:
    existing = await session.scalar(select(User.id).where(User.email == data.email))
    if existing:
        raise ConflictError(AuthEntity.USER, data.email)
    user = User(
        email=data.email,
        name=data.name,
        password_hash=await security.hash_password_async(data.password),
        instance_role=data.instance_role,
        source=UserSource.LOCAL,  # spec 84: password accounts are "local"
    )
    session.add(user)
    await session.flush()
    await events.emit(
        session,
        event_type=AuthEvent.USER_CREATED,
        entity_type=AuthEntity.USER,
        entity_id=user.id,
        actor_id=actor_id,
        payload={"email": user.email, "name": user.name, "instance_role": user.instance_role},
    )
    return user


def _user_filters(
    query,
    *,
    q: str | None,
    source: UserSource | None,
    active: bool | None,
    sources_excluded: Iterable[UserSource] | None = None,
):
    """THE directory filter (RADD-936). One builder, two callers.

    `list_users` and `count_users` used to construct this predicate separately,
    and the copies drifted: the count filtered on `User.is_active`, a column that
    does not exist, so every paginated + status-filtered request 500'd — which is
    exactly and only what Settings → Users sends. Neither `?active=true` nor
    `?limit=25` alone touches the broken line, so nothing else on the instance
    ever hit it.

    `sources_excluded` (RADD-1034) is a SEPARATE knob from `source`: the latter
    is an admin exact-match filter (Settings → Users' dropdown), the former is
    a caller-side exclusion set (`/users/directory`'s default hiding of
    `UserSource.EMAIL`). Keeping them distinct means the directory's default
    exclusion never has to fight an admin's explicit `?source=email` request —
    only `/users/directory` ever passes `sources_excluded`.
    """
    if q:
        pattern = ilike_term(q)
        query = query.where(User.email.ilike(pattern) | User.name.ilike(pattern))
    if source is not None:
        query = query.where(User.source == source.value)
    if active is not None:
        query = query.where(User.active == active)
    if sources_excluded:
        query = query.where(User.source.notin_([s.value for s in sources_excluded]))
    return query


async def list_users(
    session: AsyncSession,
    q: str | None = None,
    source: UserSource | None = None,
    active: bool | None = None,
    limit: int | None = None,
    offset: int = 0,
    sources_excluded: Iterable[UserSource] | None = None,
) -> list[User]:
    """User directory, optionally filtered (spec 84): q matches email OR name
    (case-insensitive substring, wildcards escaped), source/active match
    exactly; limit/offset page (RADD-883). `sources_excluded` (RADD-1034) is an
    additional exclusion set on top of `source`/`active`, used by the member
    directory to hide requester accounts by default — every OTHER caller
    (Settings → Users, the MCP `list_users` tool, the Jira importer's email
    lookup) leaves it unset and is unaffected."""
    query = _user_filters(
        select(User).order_by(User.created_at),
        q=q,
        source=source,
        active=active,
        sources_excluded=sources_excluded,
    )
    if limit is not None:
        query = query.offset(offset).limit(limit)
    return list((await session.execute(query)).scalars())


async def count_users(
    session: AsyncSession,
    q: str | None = None,
    source: UserSource | None = None,
    active: bool | None = None,
    sources_excluded: Iterable[UserSource] | None = None,
) -> int:
    """Pre-pagination count for the directory/admin lists (RADD-883). Shares
    `_user_filters` with `list_users` — the count and the page must answer the
    same question, and they stopped doing so once the predicate was written
    twice. `sources_excluded` must match whatever `list_users` was called with
    (RADD-1034), same reasoning as `source`/`active` above."""
    query = _user_filters(
        select(func.count()).select_from(User),
        q=q,
        source=source,
        active=active,
        sources_excluded=sources_excluded,
    )
    return (await session.execute(query)).scalar_one()


async def get_user(session: AsyncSession, user_id: uuid.UUID) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise NotFoundError(AuthEntity.USER, user_id)
    return user


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    return await session.scalar(select(User).where(User.email == email.strip().lower()))


async def users_by_ids(session: AsyncSession, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, User]:
    result = await session.execute(select(User).where(User.id.in_(set(ids))))
    return {user.id: user for user in result.scalars()}


def user_ref(user: User | None) -> dict[str, str] | None:
    """`{id, name, email}` for an event payload (RADD-922).

    One shape for every person named in the stream. Emitters used to write bare
    `author_id` / `requester` / `user_id` columns, so a webhook body or a chat
    message that wanted to say WHO had to resolve a uuid it was handed — and
    mostly did not, and printed the uuid."""
    if user is None:
        return None
    return {"id": str(user.id), "name": user.name, "email": user.email}


async def user_ref_by_id(
    session: AsyncSession, user_id: uuid.UUID | None
) -> dict[str, str] | None:
    if user_id is None:
        return None
    return user_ref((await users_by_ids(session, [user_id])).get(user_id))


async def users_by_emails(session: AsyncSession, emails: Iterable[str]) -> dict[str, User]:
    """email (lowercased) → User for the given set — the directory-reconcile
    matcher (spec 84): unknown directory members simply don't resolve."""
    wanted = {email.strip().lower() for email in emails if email}
    if not wanted:
        return {}
    result = await session.execute(select(User).where(User.email.in_(wanted)))
    return {user.email: user for user in result.scalars()}


async def revoke_sessions(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Kill every live session for the user — the one seam both deactivation
    paths (admin PATCH, spec-85 directory sync) revoke through."""
    await session.execute(delete(UserSession).where(UserSession.user_id == user_id))


async def deactivate_user(
    session: AsyncSession, user: User, actor_id: uuid.UUID | None = None
) -> bool:
    """Directory-sync deactivation (spec 85): the spec-84 PATCH semantics —
    active=False + immediate session revocation + a user.updated event — without
    an acting admin (the loop has none). Returns False when already inactive."""
    if not user.active:
        return False
    user.active = False
    await revoke_sessions(session, user.id)
    await session.flush()
    await events.emit(
        session,
        event_type=AuthEvent.USER_UPDATED,
        entity_type=AuthEntity.USER,
        entity_id=user.id,
        actor_id=actor_id,
        payload={"action": UserChange.DIRECTORY_DEACTIVATED, "active": False},
    )
    return True


async def update_user_admin(
    session: AsyncSession, user_id: uuid.UUID, data: UserAdminUpdate, actor: User
) -> User:
    """PATCH /users/{id} (spec 84, instance admin): rename and (de)activate.
    Deactivating REVOKES the user's sessions immediately (tokens are already
    dead while inactive — every auth lookup checks User.active) and blocks all
    three login paths. Deactivating yourself is refused (409)."""
    user = await get_user(session, user_id)
    changes: dict[str, object] = {}
    if data.name is not None and data.name != user.name:
        user.name = data.name
        changes["name"] = data.name
    if data.active is not None and data.active != user.active:
        if not data.active and user.id == actor.id:
            raise ConflictError(AuthEntity.USER, reason="you cannot deactivate your own account")
        user.active = data.active
        changes["active"] = data.active
        if not data.active:
            await revoke_sessions(session, user.id)
    # Spec 86: instance_role is THE role ladder (the members endpoints are gone).
    if data.instance_role is not None and data.instance_role.value != user.instance_role:
        if data.instance_role is not InstanceRole.ADMIN and user.id == actor.id:
            raise ConflictError(AuthEntity.USER, reason="you cannot demote your own account")
        user.instance_role = data.instance_role.value
        changes["instance_role"] = data.instance_role.value
    if not changes:
        return user
    await session.flush()
    await events.emit(
        session,
        event_type=AuthEvent.USER_UPDATED,
        entity_type=AuthEntity.USER,
        entity_id=user.id,
        actor_id=actor.id,
        payload={"action": UserChange.ADMIN_UPDATED, **changes},
    )
    return user


def find_duplicate_groups(users: Iterable[User]) -> list[tuple[DuplicateKind, str, list[User]]]:
    """Pure duplicates heuristic (spec 84): accounts sharing a lowercased email
    LOCAL PART (exact — dots kept) or an exact case-insensitive name. Inactive
    accounts are included (the read model carries `active`). Groups whose
    membership is identical under both keys are reported once (email wins)."""
    by_local: dict[str, list[User]] = {}
    by_name: dict[str, list[User]] = {}
    for user in users:
        by_local.setdefault(user.email.split("@", 1)[0].lower(), []).append(user)
        name = user.name.strip().lower()
        if name:
            by_name.setdefault(name, []).append(user)
    groups: list[tuple[DuplicateKind, str, list[User]]] = []
    seen: set[frozenset[uuid.UUID]] = set()
    for kind, buckets in ((DuplicateKind.EMAIL_LOCAL_PART, by_local), (DuplicateKind.NAME, by_name)):
        for key in sorted(buckets):
            members = buckets[key]
            ids = frozenset(u.id for u in members)
            if len(ids) < 2 or ids in seen:
                continue
            seen.add(ids)
            groups.append((kind, key, sorted(members, key=lambda u: (u.email, str(u.id)))))
    return groups


async def duplicate_user_groups(
    session: AsyncSession,
) -> list[tuple[DuplicateKind, str, list[User]]]:
    return find_duplicate_groups(await list_users(session))


async def authenticate(session: AsyncSession, email: str, password: str) -> User:
    user = await get_user_by_email(session, email)
    password_ok = await security.verify_password_async(password, user.password_hash if user else None)
    if user is None or not user.active or not password_ok:
        raise UnauthorizedError(BAD_CREDENTIALS)
    return user


# --- TOTP / MFA (spec 48) — local-password accounts only; SSO/LDAP IdPs own MFA ---


async def totp_row(session: AsyncSession, user_id: uuid.UUID) -> UserTotp | None:
    return await session.get(UserTotp, user_id)


async def totp_required(session: AsyncSession, user: User) -> bool:
    row = await totp_row(session, user.id)
    return row is not None and row.confirmed_at is not None


async def totp_setup(session: AsyncSession, user: User) -> UserTotp:
    """New pending secret (replaces an unconfirmed one; 409 while confirmed —
    disable first, with a valid code)."""
    row = await totp_row(session, user.id)
    if row is not None and row.confirmed_at is not None:
        raise ConflictError(AuthEntity.USER, "TOTP is already enabled — disable it first")
    if row is not None:
        await session.delete(row)
        await session.flush()
    row = UserTotp(user_id=user.id, secret=totp.generate_secret())
    session.add(row)
    await session.flush()
    return row


async def totp_confirm(session: AsyncSession, user: User, code: str) -> list[str]:
    """Confirm enrollment and mint the recovery codes in the same breath
    (RADD-677): the one moment the user is provably holding their
    authenticator is the one moment the fallback must be handed over —
    a later "generate codes" step is the step nobody does."""
    row = await totp_row(session, user.id)
    if row is None:
        raise NotFoundError(AuthEntity.USER, "no pending TOTP setup")
    if not totp.verify_code(row.secret, code, int(time.time())):
        raise UnauthorizedError("invalid TOTP code")
    row.confirmed_at = security.utcnow()
    await session.flush()
    return await _mint_recovery_codes(session, user.id)


async def _mint_recovery_codes(session: AsyncSession, user_id: uuid.UUID) -> list[str]:
    """Replace-all: old codes (used and unused) die with the new batch, so a
    leaked printout is invalidated by regenerating."""
    await session.execute(
        delete(TotpRecoveryCode).where(TotpRecoveryCode.user_id == user_id)
    )
    codes = totp.generate_recovery_codes()
    for code in codes:
        session.add(
            TotpRecoveryCode(user_id=user_id, code_hash=totp.hash_recovery_code(code))
        )
    await session.flush()
    return codes


async def regenerate_recovery_codes(session: AsyncSession, user: User, code: str) -> list[str]:
    """A fresh batch, gated on a live TOTP code — a hijacked session must not
    mint itself a quiet back door (the totp_disable precedent)."""
    row = await totp_row(session, user.id)
    if row is None or row.confirmed_at is None:
        raise NotFoundError(AuthEntity.USER, "TOTP is not enabled")
    if not totp.verify_code(row.secret, code, int(time.time())):
        raise UnauthorizedError("invalid TOTP code")
    return await _mint_recovery_codes(session, user.id)


async def recovery_codes_remaining(session: AsyncSession, user_id: uuid.UUID) -> int:
    return (
        await session.scalar(
            select(func.count())
            .select_from(TotpRecoveryCode)
            .where(TotpRecoveryCode.user_id == user_id, TotpRecoveryCode.used_at.is_(None))
        )
    ) or 0


async def totp_disable(session: AsyncSession, user: User, code: str) -> None:
    """Code required — a hijacked session must not silently strip MFA. A
    recovery code is accepted too: losing the phone is exactly when disabling
    MFA to re-enroll is the legitimate move."""
    row = await totp_row(session, user.id)
    if row is None:
        raise NotFoundError(AuthEntity.USER, "TOTP is not enabled")
    if not totp.verify_code(row.secret, code, int(time.time())) and not (
        await _consume_recovery_code(session, user.id, code)
    ):
        raise UnauthorizedError("invalid TOTP code")
    await session.execute(
        delete(TotpRecoveryCode).where(TotpRecoveryCode.user_id == user.id)
    )
    await session.delete(row)
    await session.flush()


async def _consume_recovery_code(session: AsyncSession, user_id: uuid.UUID, code: str) -> bool:
    """Burn a matching unused code. Single-use is enforced by used_at, kept
    (not deleted) so "3 of 10 left" and "when was one used" stay answerable."""
    if not totp.looks_like_recovery_code(code):
        return False
    row = await session.scalar(
        select(TotpRecoveryCode).where(
            TotpRecoveryCode.user_id == user_id,
            TotpRecoveryCode.code_hash == totp.hash_recovery_code(code),
            TotpRecoveryCode.used_at.is_(None),
        )
    )
    if row is None:
        return False
    row.used_at = security.utcnow()
    await session.flush()
    return True


async def authenticate_with_totp(
    session: AsyncSession, email: str, password: str, code: str
) -> User:
    """Stateless second step: password re-verified WITH the code; uniform 401."""
    user = await authenticate(session, email, password)
    row = await totp_row(session, user.id)
    if row is None or row.confirmed_at is None:
        raise UnauthorizedError(BAD_CREDENTIALS)
    if totp.verify_code(row.secret, code, int(time.time())):
        return user
    # RADD-677: a recovery code works wherever the TOTP code does — single-use,
    # burned before the session is minted. Same uniform 401 otherwise.
    if await _consume_recovery_code(session, user.id, code):
        return user
    raise UnauthorizedError(BAD_CREDENTIALS)


async def update_profile(session: AsyncSession, user: User, data: ProfileUpdate) -> User:
    """Self-service profile edit (spec 34): name, avatar, timezone. Email and
    roles are NOT editable here (user.manage endpoints own those)."""
    fields_set = data.model_fields_set
    if data.name is not None:
        user.name = data.name
    if "avatar_color" in fields_set:
        user.avatar_color = data.avatar_color
    if "avatar_emoji" in fields_set:
        user.avatar_emoji = data.avatar_emoji
    if data.timezone is not None:
        user.timezone = data.timezone
    await session.flush()
    await events.emit(
        session,
        event_type=AuthEvent.USER_UPDATED,
        entity_type=AuthEntity.USER,
        entity_id=user.id,
        actor_id=user.id,
        payload={"action": UserChange.PROFILE_UPDATED},
    )
    return user
