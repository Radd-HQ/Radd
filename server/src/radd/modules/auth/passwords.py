"""Changing a local password (RADD-1529).

`password_hash` used to be written twice in the whole codebase: when a user was
created and by the seed CLI. Nothing changed it afterwards, so the seeded admin
password stayed whatever was typed on a command line and a leaked password
could not be rotated without shell access.

Two paths, and only for accounts that HAVE a local password — a directory or
SSO account's password is its provider's business:

- the person changes their own, proving the current one, and every OTHER
  session of theirs ends;
- an administrator sets a new one for somebody else, and ALL of that person's
  sessions end.

Both are in the ledger. Neither event carries the password or its hash.
"""

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, ForbiddenError, UnauthorizedError
from radd.modules.events import service as events

from . import security
from .models import User, UserSession
from .types import AuthEntity, AuthEvent, InstanceRole

#: Said for a wrong current password. Deliberately not the login message: the
#: person is signed in, so there is no account to conceal.
WRONG_CURRENT_PASSWORD = "the current password is not correct"
NO_LOCAL_PASSWORD = (
    "this account has no Radd password: it signs in through its directory or identity provider"
)


def has_local_password(user: User) -> bool:
    """Whether Radd itself holds this account's password. The UI offers the
    change and the reset only when it does."""
    return user.has_local_password


def _require_local(user: User) -> None:
    if not has_local_password(user):
        raise ConflictError(AuthEntity.USER, reason=NO_LOCAL_PASSWORD)


async def change_own(
    session: AsyncSession,
    user: User,
    *,
    current_password: str,
    new_password: str,
    keep_token_hash: str | None,
) -> int:
    """Set a new password for `user`, who proves the current one. Every other
    session of theirs is revoked; the one making the request (`keep_token_hash`)
    stays. Returns how many sessions ended."""
    _require_local(user)
    if not await security.verify_password_async(current_password, user.password_hash):
        raise UnauthorizedError(WRONG_CURRENT_PASSWORD)
    if await security.verify_password_async(new_password, user.password_hash):
        raise ConflictError(AuthEntity.USER, reason="the new password is the current one")
    user.password_hash = await security.hash_password_async(new_password)
    statement = delete(UserSession).where(UserSession.user_id == user.id)
    if keep_token_hash is not None:
        statement = statement.where(UserSession.token_hash != keep_token_hash)
    ended = (await session.execute(statement)).rowcount or 0
    await session.flush()
    await events.emit(
        session,
        event_type=AuthEvent.PASSWORD_CHANGED,
        entity_type=AuthEntity.USER,
        entity_id=user.id,
        actor_id=user.id,
        payload={"target": user.email, "sessions_ended": ended},
    )
    return ended


async def admin_set(
    session: AsyncSession, *, admin: User, target: User, new_password: str
) -> int:
    """An administrator sets `target`'s password. Every session of theirs ends:
    whoever knew the old password is out. Returns how many."""
    if target.id == admin.id:
        # Their own change must prove the current password, like anyone's.
        raise ConflictError(AuthEntity.USER, reason="change your own password in Profile")
    _require_local(target)
    if target.instance_role == InstanceRole.ADMIN and admin.instance_role != InstanceRole.ADMIN:
        # user.manage alone must not become "sign in as an instance admin".
        raise ForbiddenError("only an instance admin can reset an instance admin's password")
    target.password_hash = await security.hash_password_async(new_password)
    ended = (
        await session.execute(delete(UserSession).where(UserSession.user_id == target.id))
    ).rowcount or 0
    await session.flush()
    await events.emit(
        session,
        event_type=AuthEvent.PASSWORD_RESET,
        entity_type=AuthEntity.USER,
        entity_id=target.id,
        actor_id=admin.id,
        payload={"admin": admin.email, "target": target.email, "sessions_ended": ended},
    )
    return ended


def token_hash_of(raw_cookie: str | None) -> str | None:
    return security.hash_token(raw_cookie) if raw_cookie else None

