"""Service accounts (spec 113): user rows with `source=service`, which
`create_session` refuses — so they authenticate by API key only, and their
keys are minted BY an admin. A user row, because every FK points at users."""

import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, NotFoundError
from radd.kernel import changes
from radd.modules.events import service as events

from . import scopes as scopes_mod
from .models import ApiToken, User
from .principals import require_not_builtin
from .schemas import ServiceAccountCreate, ServiceAccountUpdate, TokenCreate
from .service_tokens import _mint_token, _naive_utc
from .types import AuthEntity, AuthEvent, InstanceRole, UserSource

#: The DEFAULT address is undeliverable, so mail to an unconfigured service
#: account goes nowhere — that is the whole guarantee (RADD-869); pickers tell
#: it from a person by `UserDirectoryEntry.source`.
SERVICE_EMAIL_DOMAIN = "service.radd.local"


def synthetic_email(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-") or "service"
    return f"{slug}@{SERVICE_EMAIL_DOMAIN}"


async def get_account(session: AsyncSession, account_id: uuid.UUID) -> User:
    user = await session.get(User, account_id)
    if user is None or user.source != UserSource.SERVICE.value:
        raise NotFoundError(AuthEntity.USER, account_id)
    return user


async def token_counts(session: AsyncSession, account_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not account_ids:
        return {}
    rows = await session.execute(
        select(ApiToken.user_id, func.count()).where(ApiToken.user_id.in_(account_ids))
        .group_by(ApiToken.user_id)
    )
    return dict(rows.all())


async def token_count(session: AsyncSession, account_id: uuid.UUID) -> int:
    return (await token_counts(session, [account_id])).get(account_id, 0)


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
    # RADD-1499: the built-in Automation account keeps its seeded meaning — a
    # deactivated one fails every connector write at authz with nothing saying why.
    require_not_builtin(account, what="edited")
    before = changes.snapshot(account, ("name", "active"))
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
        changes=changes.diff_object(account, before),
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
    return await _mint_token(
        session,
        account.id,
        data.name,
        expires_at=_naive_utc(data.expires_at),
        scopes=scope.to_json() if scope is not None else None,
    )


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
