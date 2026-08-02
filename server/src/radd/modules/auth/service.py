import logging
import time
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.exceptions import ConflictError, NotFoundError, UnauthorizedError
from radd.modules.events import service as events

from . import scopes, security, totp
from .models import ApiToken, User, UserSession, UserTotp
from .schemas import ProfileUpdate, TokenCreate, UserAdminUpdate, UserCreate
from .types import (
    PAT_PREFIX_DISPLAY_CHARS,
    AuthEntity,
    AuthEvent,
    DuplicateKind,
    InstanceRole,
    UserChange,
    UserSource,
)

logger = logging.getLogger(__name__)

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
        password_hash=security.hash_password(data.password),
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


async def list_users(
    session: AsyncSession,
    q: str | None = None,
    source: UserSource | None = None,
    active: bool | None = None,
) -> list[User]:
    """User directory, optionally filtered (spec 84): q matches email OR name
    (case-insensitive substring), source/active match exactly."""
    query = select(User).order_by(User.created_at)
    if q:
        pattern = f"%{q.strip()}%"
        query = query.where(User.email.ilike(pattern) | User.name.ilike(pattern))
    if source is not None:
        query = query.where(User.source == source.value)
    if active is not None:
        query = query.where(User.active == active)
    return list((await session.execute(query)).scalars())


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
    password_ok = security.verify_password(password, user.password_hash if user else None)
    if user is None or not user.active or not password_ok:
        raise UnauthorizedError(BAD_CREDENTIALS)
    return user


# --- sessions ---


async def create_session(session: AsyncSession, user: User) -> str:
    """Returns the raw session token (goes into the cookie; only its hash is stored).

    Also stamps `last_login_at` (spec 84): sessions are minted exclusively by
    the login endpoints (local + TOTP, LDAP, OIDC), so this one seam covers
    every successful sign-in path."""
    # Spec 113: a service account authenticates by API key and nothing else.
    # Refusing here covers local, TOTP, LDAP and OIDC at once, because every one
    # of those paths mints its session through this function.
    if user.source == UserSource.SERVICE:
        raise UnauthorizedError("service accounts authenticate with an API key")
    token = security.new_session_token()
    session.add(
        UserSession(
            user_id=user.id,
            token_hash=security.hash_token(token),
            expires_at=security.utcnow() + timedelta(hours=settings.session_ttl_hours),
        )
    )
    user.last_login_at = security.utcnow()
    await session.flush()
    return token


async def delete_session_by_token(session: AsyncSession, token: str) -> None:
    await session.execute(
        delete(UserSession).where(UserSession.token_hash == security.hash_token(token))
    )


async def user_for_session_token(session: AsyncSession, token: str) -> User | None:
    return await session.scalar(
        select(User)
        .join(UserSession, UserSession.user_id == User.id)
        .where(
            UserSession.token_hash == security.hash_token(token),
            UserSession.expires_at > security.utcnow(),
            User.active,
        )
    )


# --- API tokens ---


async def create_api_token(
    session: AsyncSession, user: User, data: TokenCreate
) -> tuple[ApiToken, str]:
    """Returns (row, raw token). The raw token is shown exactly once."""
    raw = security.new_api_token()
    # Spec 113: a personal token may narrow itself too — same vocabulary, same
    # intersection. Omitted stays NULL, so existing behaviour is untouched.
    scope = scopes.parse_scope(data.scopes)  # ValueError -> 422 at the router
    token = ApiToken(
        user_id=user.id,
        name=data.name,
        token_hash=security.hash_token(raw),
        prefix_display=raw[:PAT_PREFIX_DISPLAY_CHARS],
        expires_at=_naive_utc(data.expires_at),
        scopes=scope.to_json() if scope is not None else None,
    )
    session.add(token)
    await session.flush()
    return token, raw


async def list_api_tokens(session: AsyncSession, user: User) -> list[ApiToken]:
    result = await session.execute(
        select(ApiToken).where(ApiToken.user_id == user.id).order_by(ApiToken.created_at)
    )
    return list(result.scalars())


async def delete_api_token(session: AsyncSession, user: User, token_id: uuid.UUID) -> None:
    token = await session.get(ApiToken, token_id)
    if token is None or token.user_id != user.id:
        raise NotFoundError(AuthEntity.API_TOKEN, token_id)
    await session.delete(token)


async def user_for_api_token(session: AsyncSession, token: str) -> User | None:
    now = security.utcnow()
    row = (
        await session.execute(
            select(ApiToken, User)
            .join(User, User.id == ApiToken.user_id)
            .where(ApiToken.token_hash == security.hash_token(token), User.active)
        )
    ).first()
    if row is None:
        return None
    api_token, user = row
    if api_token.expires_at is not None and api_token.expires_at <= now:
        return None
    throttle = timedelta(seconds=settings.token_last_used_throttle_seconds)
    if api_token.last_used_at is None or now - api_token.last_used_at >= throttle:
        api_token.last_used_at = now
    # Spec 113: the key's scope rides on the principal, so every downstream
    # `authz.effective_permissions` intersects with it. A stored scope that no
    # longer parses (an atom removed by an upgrade) must not silently widen the
    # key — it is refused instead.
    if api_token.scopes is not None:
        try:
            user.token_scope = scopes.parse_scope(api_token.scopes)
        except ValueError:
            logger.warning("api token %s carries an unparseable scope; refusing it", api_token.id)
            return None
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


async def totp_confirm(session: AsyncSession, user: User, code: str) -> None:
    row = await totp_row(session, user.id)
    if row is None:
        raise NotFoundError(AuthEntity.USER, "no pending TOTP setup")
    if not totp.verify_code(row.secret, code, int(time.time())):
        raise UnauthorizedError("invalid TOTP code")
    row.confirmed_at = security.utcnow()
    await session.flush()


async def totp_disable(session: AsyncSession, user: User, code: str) -> None:
    """Code required — a hijacked session must not silently strip MFA."""
    row = await totp_row(session, user.id)
    if row is None:
        raise NotFoundError(AuthEntity.USER, "TOTP is not enabled")
    if not totp.verify_code(row.secret, code, int(time.time())):
        raise UnauthorizedError("invalid TOTP code")
    await session.delete(row)
    await session.flush()


async def authenticate_with_totp(
    session: AsyncSession, email: str, password: str, code: str
) -> User:
    """Stateless second step: password re-verified WITH the code; uniform 401."""
    user = await authenticate(session, email, password)
    row = await totp_row(session, user.id)
    if (
        row is None
        or row.confirmed_at is None
        or not totp.verify_code(row.secret, code, int(time.time()))
    ):
        raise UnauthorizedError(BAD_CREDENTIALS)
    return user


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


def _naive_utc(dt: datetime | None) -> datetime | None:
    if dt is None or dt.tzinfo is None:
        return dt
    return dt.astimezone(UTC).replace(tzinfo=None)


# --- user merge (duplicate identities: seed + AD import + Jira import) ---
#
# Deliberate module-boundary exception: merging an identity is a cross-cutting
# maintenance operation on the user id itself, so auth (the owner of users)
# repoints every referencing column by raw SQL rather than importing every other
# module (which would invert the dependency graph — most modules import auth).
# KEEP THESE LISTS IN SYNC when a new table references a user id.

# Plain repoint: UPDATE … SET col = target WHERE col = source.
_MERGE_REPOINT: tuple[tuple[str, str], ...] = (
    ("work_items", "assignee_id"),
    ("work_items", "reporter_id"),
    ("comments", "author_id"),
    ("worklogs", "author_id"),
    # A MERGE asserts one person, so their leave follows them. Hard DELETE
    # destroys leave first (below), same rule as worklogs — a successor must
    # not show as on vacation they never took.
    ("leave_periods", "user_id"),
    ("leave_periods", "created_by"),
    ("notifications", "user_id"),
    ("notifications", "actor_id"),
    ("events", "actor_id"),
    ("item_web_links", "created_by"),
    ("item_vcs_links", "created_by"),
    ("attachments", "created_by"),
    ("pages", "created_by"),
    ("page_versions", "author_id"),
    ("item_page_links", "created_by"),
    ("views", "owner_id"),
    ("item_participants", "added_by"),
    ("view_members", "added_by"),  # roadmap wave: who pinned the item to the view
    ("dashboards", "owner_id"),
    # Spec 89: these three block a hard delete (FK NO ACTION) and were ALSO
    # missing from the merge — a merged-away account kept holding its approvals
    # and doc edits. Found by diffing this list against every FK to users.id.
    ("approval_requests", "requested_by"),
    ("approval_votes", "user_id"),
    ("pages", "updated_by"),
    # Teams the person owns follow them; the column is ON DELETE SET NULL, so
    # without this a delete would silently leave those teams ownerless.
    ("teams", "owner_id"),
    # Spec 100: who ran an import / dry run / rollback. The successor inherits it
    # (operational history), rather than the run becoming anonymous.
    ("jira_runs", "actor_id"),
    # Spec 99: who took a backup / owns a schedule. SET NULL, so a delete would
    # quietly blank the operational history rather than hand it to the survivor.
    ("backup_runs", "actor_id"),
    ("backup_schedules", "created_by_id"),
    # Spec 100: who downloaded a Jira snapshot. SET NULL, same reasoning — the
    # successor inherits the cached download rather than it becoming anonymous.
    ("jira_snapshots", "actor_id"),
    # Spec 110: federated logins follow the person. Merging the AD account into
    # the Google one (or back) must not cost either account its ability to sign
    # in — CASCADE would have destroyed the source's identities outright. Not in
    # _MERGE_DEDUPE: uniqueness is (provider_id, subject), so a survivor holding
    # two identities from one provider is legal and correct — it just means the
    # person had two accounts there, and now both open the same Radd user.
    ("user_identities", "user_id"),
)
# (entity_col, user_col) unique pairs: drop source rows the target already has,
# then repoint the rest.
# (entity_cols, user_col): the entity columns are what makes a row UNIQUE per
# user, so a source row the target already holds is a COLLISION — dropped rather
# than repointed onto a duplicate key. Comparison is null-safe
# (`IS NOT DISTINCT FROM`), because a scope column can legitimately be NULL:
# `global_role_grants.project_id IS NULL` means the grant is global (spec 91),
# and `=` never matches NULL, so a plain equality check would let two "same"
# global grants through and violate the unique index.
_MERGE_DEDUPE: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("item_watchers", ("item_id",), "user_id"),
    ("item_stars", ("item_id",), "user_id"),
    ("project_members", ("project_id",), "user_id"),
    ("team_members", ("team_id",), "user_id"),
    ("item_participants", ("item_id",), "user_id"),
    ("form_shares", ("form_id",), "user_id"),
    # Spec 87, found by the audit: both are CASCADE, so a merge that
    # DELETES the source (as it now does) silently destroyed them instead of
    # transferring. Merging an account must not cost the person their granted
    # roles or the teams they manage.
    ("team_managers", ("team_id",), "user_id"),
    ("global_role_grants", ("role_id", "project_id"), "user_id"),
    # dashboard_shares is gone — dashboard sharing lives in access_grants now
    # (spec 92 adopters), which `_repoint_user_access_grants` already handles
    # generically for EVERY resource type. Same reason view_shares isn't here.
)
# Credentials/preferences are identity-private — the target keeps its own.
_MERGE_PURGE: tuple[str, ...] = ("sessions", "api_tokens", "user_totp", "notification_prefs")


def _dedupe_sql(table: str, entity_cols: tuple[str, ...], user_col: str) -> str:
    """Drop the source's rows that the target ALREADY holds, so the repoint that
    follows cannot collide with a unique index. Null-safe on every entity column
    — see `_MERGE_DEDUPE`."""
    match = " AND ".join(f"o.{col} IS NOT DISTINCT FROM t.{col}" for col in entity_cols)
    return (
        f"DELETE FROM {table} t WHERE t.{user_col} = :src AND EXISTS ("
        f"SELECT 1 FROM {table} o WHERE {match} AND o.{user_col} = :dst)"
    )


async def _repoint_user_access_grants(
    session: AsyncSession, source_id: uuid.UUID, target_id: uuid.UUID
) -> None:
    """Move a user's ACCESS GRANTS (spec 92 — view shares, user-subject field
    grants) to the target. `subject_id` is polymorphic (no FK), so it isn't caught
    by the FK-based repoint list; dedupe on the full grant identity first, then
    repoint the USER subject."""
    from sqlalchemy import text as sql

    await session.execute(
        sql(
            "DELETE FROM access_grants t WHERE t.subject_type='user' AND t.subject_id=:src "
            "AND EXISTS (SELECT 1 FROM access_grants o WHERE o.subject_type='user' "
            "AND o.subject_id=:dst AND o.resource_type=t.resource_type "
            "AND o.resource_id=t.resource_id AND o.access=t.access "
            "AND o.project_id IS NOT DISTINCT FROM t.project_id)"
        ),
        {"src": source_id, "dst": target_id},
    )
    await session.execute(
        sql(
            "UPDATE access_grants SET subject_id=:dst "
            "WHERE subject_type='user' AND subject_id=:src"
        ),
        {"src": source_id, "dst": target_id},
    )


async def ensure_imported_user(
    session: AsyncSession,
    *,
    email: str,
    name: str,
    source: UserSource,
    actor_id: uuid.UUID | None = None,
) -> tuple[User, bool]:
    """Find-or-create a PASSWORD-LESS account for someone an importer named.

    The public seam behind Jira's placeholder people (spec 90 follow-up): an
    importer must never hand-build a `User` row, and must never silently credit
    an unknown author to whoever ran the import.

    ACTIVE, because the items service refuses an inactive assignee; password-less,
    because a placeholder must not be a way in. Returns (user, created) and is
    idempotent on email, so a re-import adopts the row it made last time.
    """
    existing = await get_user_by_email(session, email)
    if existing is not None:
        return existing, False
    user = User(
        email=email.strip().lower(),
        name=name.strip() or email.split("@")[0],
        password_hash=None,
        source=source.value,
    )
    session.add(user)
    await session.flush()
    await events.emit(
        session,
        event_type=AuthEvent.USER_CREATED,
        entity_type=AuthEntity.USER,
        entity_id=user.id,
        actor_id=actor_id,
        payload={"email": user.email, "name": user.name, "source": user.source},
    )
    return user, True


async def merge_users(
    session: AsyncSession,
    source_id: uuid.UUID,
    target_id: uuid.UUID,
    actor_id: uuid.UUID | None = None,
) -> User:
    """Fold `source` into `target`: every reference (items, comments, worklogs,
    watchers, memberships, history…) repoints to the target; the source's
    credentials are revoked and the account deactivated (kept for audit)."""
    from sqlalchemy import text as sql

    if source_id == target_id:
        raise ConflictError(AuthEntity.USER, reason="cannot merge a user into itself")
    source = await get_user(session, source_id)
    target = await get_user(session, target_id)
    for table, entity_cols, user_col in _MERGE_DEDUPE:
        await session.execute(sql(_dedupe_sql(table, entity_cols, user_col)),
                              {"src": source_id, "dst": target_id})
        await session.execute(
            sql(f"UPDATE {table} SET {user_col} = :dst WHERE {user_col} = :src"),
            {"src": source_id, "dst": target_id},
        )
    for table, column in _MERGE_REPOINT:
        await session.execute(
            sql(f"UPDATE {table} SET {column} = :dst WHERE {column} = :src"),
            {"src": source_id, "dst": target_id},
        )
    await _repoint_user_access_grants(session, source_id, target_id)
    for table in _MERGE_PURGE:
        await session.execute(
            sql(f"DELETE FROM {table} WHERE user_id = :src"), {"src": source_id}
        )
    # A merge asserts these two rows are the SAME PERSON, so the survivor keeps
    # that person's standing — their privileges must not depend on which row
    # happened to win. Without this, folding an admin into a member (the normal
    # direction when an AD import adopts a local account) silently demotes them,
    # and if that was the only admin the instance is left with no way back in
    # short of direct database access.
    if InstanceRole(source.instance_role) is InstanceRole.ADMIN:
        target.instance_role = InstanceRole.ADMIN.value
    await session.flush()

    # The source is DELETED, not deactivated. Everything it owned has
    # just moved to the target, so the row holds nothing; keeping a dead duplicate
    # of the same person around only cluttered pickers and left "who is this?"
    # accounts behind every AD adoption.
    #
    # Note this is NOT `delete_user`: that destroys worklogs first, on the spec-89
    # principle that nobody should be credited with hours they didn't work. That
    # protects a delete-and-reassign, which hands one person's work to ANOTHER. A
    # merge asserts one person, so their hours follow them — `_MERGE_REPOINT` has
    # already moved the worklogs above, and the row it deletes has none left.
    #
    # Emitted BEFORE the delete: the trail keeps the email and name of an account
    # that is about to stop existing.
    await events.emit(
        session,
        event_type=AuthEvent.USER_DELETED,
        entity_type=AuthEntity.USER,
        entity_id=source.id,
        actor_id=actor_id,
        payload={
            "action": "merged",
            "email": source.email,
            "name": source.name,
            "into": str(target.id),
            "into_email": target.email,
        },
    )
    await session.delete(source)
    await session.flush()
    return target


# What a delete would hand to the successor, in the words the dialog uses. Counted
# from the same columns the repoint moves, so the preview cannot drift from the act.
_CONTENT_COUNTS: tuple[tuple[str, str, str], ...] = (
    ("reported_items", "work_items", "reporter_id"),
    ("assigned_items", "work_items", "assignee_id"),
    ("comments", "comments", "author_id"),
    ("documents", "pages", "created_by"),
    ("views", "views", "owner_id"),
    ("dashboards", "dashboards", "owner_id"),
    ("owned_teams", "teams", "owner_id"),
    ("attachments", "attachments", "created_by"),
    ("approvals", "approval_requests", "requested_by"),
)


async def user_content_summary(session: AsyncSession, user_id: uuid.UUID) -> dict[str, int]:
    """What this account owns (spec 89) — drives the delete dialog's "these move
    to…" line, and answers whether a successor is needed at all.

    `worklogs` is reported separately because deletion DISCARDS it rather than
    reassigning: crediting a successor with hours they never worked would corrupt
    every timesheet and time report that includes them.
    """
    from sqlalchemy import text as sql

    summary: dict[str, int] = {}
    for label, table, column in _CONTENT_COUNTS:
        count = await session.scalar(
            sql(f"SELECT count(*) FROM {table} WHERE {column} = :u"), {"u": user_id}
        )
        summary[label] = int(count or 0)
    summary["worklogs"] = int(
        await session.scalar(
            sql("SELECT count(*) FROM worklogs WHERE author_id = :u"), {"u": user_id}
        )
        or 0
    )
    summary["worklog_seconds"] = int(
        await session.scalar(
            sql("SELECT COALESCE(sum(time_spent_seconds), 0) FROM worklogs WHERE author_id = :u"),
            {"u": user_id},
        )
        or 0
    )
    return summary


def ensure_deletable(user: User, actor: User, successor: User | None, owns: bool) -> None:
    """Pure guards for a hard delete (spec 89), unit-tested.

    Deleting yourself is refused for the same reason self-demotion is: the actor
    would vanish mid-request. A successor is required only when there is
    something to inherit, so emptying out placeholder accounts stays one click.
    """
    if user.id == actor.id:
        raise ConflictError(AuthEntity.USER, reason="you cannot delete your own account")
    if owns and successor is None:
        raise ConflictError(
            AuthEntity.USER,
            reason=f"{user.email} owns work — name someone to inherit it (reassign_to)",
        )
    if successor is not None:
        if successor.id == user.id:
            raise ConflictError(
                AuthEntity.USER, reason="the successor cannot be the account being deleted"
            )
        if not successor.active:
            raise ConflictError(
                AuthEntity.USER,
                reason=f"{successor.email} is deactivated and cannot inherit the work",
            )


async def delete_user(
    session: AsyncSession,
    user_id: uuid.UUID,
    successor_id: uuid.UUID | None = None,
    actor: User | None = None,
) -> dict[str, int]:
    """HARD-delete an account, handing everything it authored to `successor_id`
    (spec 89). Returns the summary of what moved.

    The row really goes — unlike `merge_users`, which keeps a deactivated shell
    for audit. Everything that would block that (13 FK columns with NO ACTION) is
    repointed first, personal state (sessions, tokens, MFA, prefs, stars,
    memberships, shares) dies with the account via purge or FK CASCADE, and
    worklogs are DELETED rather than reassigned so nobody is credited with hours
    they did not work.
    """
    from sqlalchemy import text as sql

    user = await get_user(session, user_id)
    successor = await get_user(session, successor_id) if successor_id else None
    summary = await user_content_summary(session, user_id)
    owns = any(
        summary[label] for label, _table, _column in _CONTENT_COUNTS
    ) or bool(summary["worklogs"])
    if actor is not None:
        ensure_deletable(user, actor, successor, owns)

    # Time records go first, so the repoint below cannot pick them up.
    await session.execute(sql("DELETE FROM worklogs WHERE author_id = :u"), {"u": user_id})
    # Leave follows the worklog rule: destroyed, never inherited — a successor
    # repointed onto someone's vacation would render as "on leave" everywhere.
    await session.execute(sql("DELETE FROM leave_periods WHERE user_id = :u"), {"u": user_id})
    if successor is not None:
        for table, entity_cols, user_col in _MERGE_DEDUPE:
            await session.execute(sql(_dedupe_sql(table, entity_cols, user_col)),
                                  {"src": user_id, "dst": successor.id})
        for table, column in _MERGE_REPOINT + tuple((t, c) for t, _e, c in _MERGE_DEDUPE):
            await session.execute(
                sql(f"UPDATE {table} SET {column} = :dst WHERE {column} = :src"),
                {"src": user_id, "dst": successor.id},
            )
        await _repoint_user_access_grants(session, user_id, successor.id)
    else:
        # No successor: the account authored nothing, but it can still be
        # referenced by columns that carry NO foreign key (events.actor_id,
        # notifications, watchers) — those would silently dangle rather than
        # error, leaving the UI resolving a ghost. Personal rows are dropped and
        # the audit link is nulled; the user.deleted event below keeps the
        # email/name, so the trail survives without pointing at a missing row.
        for table in ("notifications", "item_watchers"):
            await session.execute(sql(f"DELETE FROM {table} WHERE user_id = :u"), {"u": user_id})
        # A gone user's access grants (view shares / user-subject field grants) just go.
        await session.execute(
            sql("DELETE FROM access_grants WHERE subject_type='user' AND subject_id = :u"),
            {"u": user_id},
        )
        await session.execute(
            sql("UPDATE events SET actor_id = NULL WHERE actor_id = :u"), {"u": user_id}
        )
        for table, column in (
            ("notifications", "actor_id"),
            ("attachments", "created_by"),
            ("item_web_links", "created_by"),
            ("item_vcs_links", "created_by"),
        ):
            await session.execute(
                sql(f"UPDATE {table} SET {column} = NULL WHERE {column} = :u"), {"u": user_id}
            )
    for table in _MERGE_PURGE:
        await session.execute(sql(f"DELETE FROM {table} WHERE user_id = :u"), {"u": user_id})

    # Emitted BEFORE the delete: events.actor_id has just been repointed, and the
    # row is about to stop existing, so this is the last chance to record it.
    await events.emit(
        session,
        event_type=AuthEvent.USER_DELETED,
        entity_type=AuthEntity.USER,
        entity_id=user.id,
        actor_id=actor.id if actor else None,
        payload={
            "email": user.email,
            "name": user.name,
            "reassigned_to": str(successor.id) if successor else None,
            "reassigned_to_email": successor.email if successor else None,
            "moved": {k: v for k, v in summary.items() if v},
        },
    )
    await session.flush()
    await session.delete(user)
    await session.flush()
    return summary
