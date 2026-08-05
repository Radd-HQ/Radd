"""Session lifecycle + admin view-as, split out of `service.py` (RADD-902)
along its own "sessions" marker (formerly lines 237-357).

`start_view_as`/`end_view_as` need `get_user` — users CRUD, which stays in
`service.py` — but import it deferred, inside the function, rather than at
module level: `service.py` imports THIS module to re-export the session API
under its own name, so a top-level cross-import here would circle straight
back into `service.py` mid-initialization.
"""

import uuid
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.exceptions import ConflictError, UnauthorizedError
from radd.modules.events import service as events

from . import security
from .models import User, UserSession
from .types import AuthEntity, AuthEvent, UserSource


async def create_session(session: AsyncSession, user: User) -> str:
    """Returns the raw session token (goes into the cookie; only its hash is stored).

    Also stamps `last_login_at` (spec 84): sessions are minted exclusively by
    the login endpoints (local + TOTP, LDAP, OIDC), so this one seam covers
    every successful sign-in path."""
    # Spec 113: a service account authenticates by API key and nothing else.
    # Refusing here covers local, TOTP, LDAP and OIDC at once, because every one
    # of those paths mints its session through this function. RADD-828: an
    # email-provisioned requester account has no credential either — mail is
    # its interface until an SSO login by the same verified email CLAIMS it.
    if user.source == UserSource.SERVICE:
        raise UnauthorizedError("service accounts authenticate with an API key")
    if user.source == UserSource.EMAIL:
        raise UnauthorizedError(
            "this account was created from an email and has no login — sign in "
            "with SSO using the same address to claim it"
        )
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


async def session_row_for_token(session: AsyncSession, token: str) -> UserSession | None:
    """The live session ROW for a cookie — the view-as endpoints act on it."""
    return await session.scalar(
        select(UserSession).where(
            UserSession.token_hash == security.hash_token(token),
            UserSession.expires_at > security.utcnow(),
        )
    )


async def resolve_session_users(
    session: AsyncSession, token: str
) -> tuple[User, User | None] | None:
    """(real user, view-as target | None) for a session cookie (RADD-836 U1).

    The real account must be live; a dangling/deactivated target degrades to
    no-impersonation rather than an error — the admin gets themselves back."""
    row = await session_row_for_token(session, token)
    if row is None:
        return None
    real = await session.get(User, row.user_id)
    if real is None or not real.active:
        return None
    target: User | None = None
    if row.view_as_user_id is not None:
        target = await session.get(User, row.view_as_user_id)
        if target is not None and not target.active:
            target = None
    return real, target


async def start_view_as(
    session: AsyncSession, *, admin: User, row: UserSession, target_id: uuid.UUID
) -> User:
    """Begin a read-only preview as `target_id` on this session (RADD-836 U1).
    Instance-admin only — the router enforces it; this validates the target and
    writes the audit event."""
    # Deferred: `get_user` is users-CRUD and stays in service.py — see the
    # module docstring for why this can't be a top-level import.
    from .service import get_user

    if target_id == admin.id:
        raise ConflictError(AuthEntity.SESSION, reason="you are already yourself")
    target = await get_user(session, target_id)
    if not target.active:
        raise ConflictError(AuthEntity.SESSION, reason="cannot preview a deactivated account")
    row.view_as_user_id = target.id
    await session.flush()
    await events.emit(
        session,
        event_type=AuthEvent.VIEW_AS_STARTED,
        entity_type=AuthEntity.USER,
        entity_id=target.id,
        actor_id=admin.id,
        payload={"admin": admin.email, "target": target.email},
    )
    return target


async def end_view_as(session: AsyncSession, *, admin: User, row: UserSession) -> None:
    if row.view_as_user_id is None:
        return
    target = await session.get(User, row.view_as_user_id)
    row.view_as_user_id = None
    await session.flush()
    await events.emit(
        session,
        event_type=AuthEvent.VIEW_AS_ENDED,
        entity_type=AuthEntity.USER,
        entity_id=target.id if target else row.user_id,
        actor_id=admin.id,
        payload={"admin": admin.email, "target": target.email if target else None},
    )
