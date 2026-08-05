"""Service accounts (spec 113): principals that authenticate by API key only.

A service account IS a user row. Every FK in the system points at `users` —
assignee, reporter, comment author, worklog author, `events.actor_id` — so an
identity that is not a user would need a parallel path through all of them for no
benefit. What makes it a service account is `source=service`, which
`create_session` refuses, and the fact that its authority comes from grants an
admin gives it rather than from a person.

Keys are ordinary `api_tokens` rows, with the spec-113 `scopes` narrowing.
Because a service account cannot log in, its keys have to be mintable BY an
admin — which is the one thing personal tokens never needed.
"""

import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, NotFoundError
from radd.modules.events import service as events

from . import scopes as scopes_mod
from . import service, security
from .models import ApiToken, User
from .schemas import ServiceAccountCreate, ServiceAccountUpdate, TokenCreate
from .types import PAT_PREFIX_DISPLAY_CHARS, AuthEntity, AuthEvent, InstanceRole, UserSource

#: Synthetic addresses live on a domain that cannot receive mail — the DEFAULT
#: address is undeliverable, so email notifications to an unconfigured service
#: account go nowhere. That is the whole guarantee (RADD-869): a caller may
#: still set a real address, the account can be assigned work and accrues
#: notification rows like anyone, and pickers rely on `UserDirectoryEntry.
#: source` (badged as a service account in the SPA) to tell it from a person.
SERVICE_EMAIL_DOMAIN = "service.radd.local"


def synthetic_email(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-") or "service"
    return f"{slug}@{SERVICE_EMAIL_DOMAIN}"


async def list_accounts(session: AsyncSession) -> list[User]:
    rows = await session.execute(
        select(User).where(User.source == UserSource.SERVICE.value).order_by(User.name)
    )
    return list(rows.scalars())


async def get_account(session: AsyncSession, account_id: uuid.UUID) -> User:
    user = await session.get(User, account_id)
    if user is None or user.source != UserSource.SERVICE.value:
        raise NotFoundError(AuthEntity.USER, account_id)
    return user


async def token_count(session: AsyncSession, account_id: uuid.UUID) -> int:
    rows = await session.execute(
        select(func.count()).select_from(ApiToken).where(ApiToken.user_id == account_id)
    )
    return int(rows.scalar_one())


async def create_account(
    session: AsyncSession, data: ServiceAccountCreate, actor_id: uuid.UUID | None = None
) -> User:
    email = (data.email or synthetic_email(data.name)).strip().lower()
    existing = await session.scalar(select(User.id).where(User.email == email))
    if existing:
        raise ConflictError(AuthEntity.USER, email)
    account = User(
        email=email,
        name=data.name,
        # No password hash at all: there is nothing to verify against, and
        # `create_session` refuses the source outright, so both doors are shut.
        password_hash="",
        instance_role=InstanceRole.MEMBER.value,
        source=UserSource.SERVICE.value,
    )
    session.add(account)
    await session.flush()
    await events.emit(
        session,
        event_type=AuthEvent.USER_CREATED,
        entity_type=AuthEntity.USER,
        entity_id=account.id,
        actor_id=actor_id,
        payload={
            "email": account.email,
            "name": account.name,
            "instance_role": account.instance_role,
            "source": UserSource.SERVICE.value,
            "description": data.description,
        },
    )
    return account


async def update_account(
    session: AsyncSession, account_id: uuid.UUID, data: ServiceAccountUpdate, actor_id: uuid.UUID
) -> User:
    account = await get_account(session, account_id)
    if data.name is not None:
        account.name = data.name
    if data.active is not None:
        account.active = data.active
    await session.flush()
    await events.emit(
        session,
        event_type=AuthEvent.USER_UPDATED,
        entity_type=AuthEntity.USER,
        entity_id=account.id,
        actor_id=actor_id,
        payload={"name": account.name, "active": account.active},
    )
    return account


async def create_key(
    session: AsyncSession, account_id: uuid.UUID, data: TokenCreate
) -> tuple[ApiToken, str]:
    """Mint a key FOR a service account. The scope is validated here rather than
    at check time: an unknown atom that silently never matches is a scope that
    looks granted and is not."""
    account = await get_account(session, account_id)
    scope = scopes_mod.parse_scope(data.scopes)  # raises ValueError -> 422
    raw = security.new_api_token()
    token = ApiToken(
        user_id=account.id,
        name=data.name,
        token_hash=security.hash_token(raw),
        prefix_display=raw[:PAT_PREFIX_DISPLAY_CHARS],
        expires_at=service._naive_utc(data.expires_at),
        scopes=scope.to_json() if scope is not None else None,
    )
    session.add(token)
    await session.flush()
    return token, raw


async def list_keys(session: AsyncSession, account_id: uuid.UUID) -> list[ApiToken]:
    await get_account(session, account_id)
    rows = await session.execute(
        select(ApiToken).where(ApiToken.user_id == account_id).order_by(ApiToken.created_at)
    )
    return list(rows.scalars())


async def revoke_key(session: AsyncSession, account_id: uuid.UUID, token_id: uuid.UUID) -> None:
    await get_account(session, account_id)
    token = await session.get(ApiToken, token_id)
    if token is None or token.user_id != account_id:
        raise NotFoundError("api_token", token_id)
    await session.delete(token)
    await session.flush()
