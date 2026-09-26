"""API tokens: personal keys, service-account keys and server-minted ephemeral keys."""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.exceptions import NotFoundError

from . import scopes, security
from .models import ApiToken, User
from .principals import require_account_session
from .schemas import TokenCreate
from .types import PAT_PREFIX_DISPLAY_CHARS, AuthEntity

logger = logging.getLogger(__name__)


def _naive_utc(dt: datetime | None) -> datetime | None:
    if dt is None or dt.tzinfo is None:
        return dt
    return dt.astimezone(UTC).replace(tzinfo=None)


async def _mint_token(
    session: AsyncSession,
    user_id: uuid.UUID,
    name: str,
    *,
    expires_at: datetime | None,
    scopes: dict | None,
    **extra,
) -> tuple[ApiToken, str]:
    """Insert a token row; returns (row, raw token). The raw token is shown once."""
    raw = security.new_api_token()
    token = ApiToken(
        user_id=user_id,
        name=name,
        token_hash=security.hash_token(raw),
        prefix_display=raw[:PAT_PREFIX_DISPLAY_CHARS],
        expires_at=expires_at,
        scopes=scopes,
        **extra,
    )
    session.add(token)
    await session.flush()
    return token, raw


async def create_api_token(
    session: AsyncSession, user: User, data: TokenCreate
) -> tuple[ApiToken, str]:
    """Returns (row, raw token). The raw token is shown exactly once."""
    require_account_session(user)
    # Spec 113: a personal token may narrow itself too; omitted stays NULL.
    scope = scopes.parse_scope(data.scopes)  # ValueError -> 422 at the router
    return await _mint_token(
        session,
        user.id,
        data.name,
        expires_at=_naive_utc(data.expires_at),
        scopes=scope.to_json() if scope is not None else None,
    )


async def mint_ephemeral_token(
    session: AsyncSession,
    user: User,
    *,
    name: str,
    ttl_seconds: int,
    automation_cause: dict | None = None,
) -> tuple[ApiToken, str]:
    """A short-lived UNSCOPED key for `user`, minted by the server for its own
    subprocess (RADD-1269: an automation's script). No API principal is
    involved, so the human-session rule does not apply; the caller deletes
    the row when the run ends and the expiry covers the case where it cannot.
    Unscoped means "exactly the account's rights" — a key can never exceed
    its account (spec 113), which is the containment the caller relies on.

    `automation_cause` (RADD-1314) marks every request made with the key as
    automation-caused — the loop guard for writes that arrive over REST."""
    from radd.clock import utcnow

    return await _mint_token(
        session,
        user.id,
        name[:200],
        expires_at=utcnow() + timedelta(seconds=max(1, ttl_seconds)),
        scopes=None,
        automation_cause=automation_cause,
    )


async def discard_token(session: AsyncSession, token: ApiToken) -> None:
    """Delete a token the server minted for itself, whoever it belongs to."""
    await session.delete(token)
    await session.flush()


async def list_api_tokens(session: AsyncSession, user: User) -> list[ApiToken]:
    require_account_session(user)
    result = await session.execute(
        select(ApiToken).where(ApiToken.user_id == user.id).order_by(ApiToken.created_at)
    )
    return list(result.scalars())


async def delete_api_token(session: AsyncSession, user: User, token_id: uuid.UUID) -> None:
    require_account_session(user)
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
    user.api_token_id = api_token.id
    user.token_scope = None
    user.automation_cause = api_token.automation_cause
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
