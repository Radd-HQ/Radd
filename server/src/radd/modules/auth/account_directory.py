"""Service-account management projections; callers own the global read gate."""

import uuid

from sqlalchemy import case, func, literal, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import ilike_term

from . import service_accounts
from .models import ApiToken, User
from .schemas import ServiceAccountRead, ServiceKeySummaryRead
from .types import UserSource


def _accounts(q: str):
    condition = User.source == UserSource.SERVICE.value
    if q.strip():
        term = ilike_term(q.strip())
        condition &= or_(User.name.ilike(term), User.email.ilike(term))
    return condition


async def accounts(
    session: AsyncSession,
    *,
    q: str = "",
    limit: int | None = None,
    offset: int = 0,
) -> list[ServiceAccountRead]:
    statement = select(
        *(getattr(User, key) for key in ServiceAccountRead.model_fields if key != "token_count")
    )
    statement = statement.where(_accounts(q)).order_by(User.name, User.id).offset(offset)
    if limit is not None:
        statement = statement.limit(limit)
    rows = (await session.execute(statement)).mappings().all()
    counts = await service_accounts.token_counts(session, [row["id"] for row in rows])
    return [ServiceAccountRead(**row, token_count=counts.get(row["id"], 0)) for row in rows]


async def account_total(session: AsyncSession, q: str) -> int:
    return await session.scalar(select(func.count()).select_from(User).where(_accounts(q))) or 0


async def by_id(session: AsyncSession, account_id: uuid.UUID) -> ServiceAccountRead:
    account = await service_accounts.get_account(session, account_id)
    return ServiceAccountRead.model_validate(account).model_copy(
        update={
            "token_count": await service_accounts.token_count(session, account_id),
        }
    )


async def keys(
    session: AsyncSession,
    account_id: uuid.UUID,
    *,
    q: str = "",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ServiceKeySummaryRead], int]:
    await service_accounts.get_account(session, account_id)
    condition = ApiToken.user_id == account_id
    if q.strip():
        term = ilike_term(q.strip())
        condition &= or_(ApiToken.name.ilike(term), ApiToken.prefix_display.ilike(term))
    total = await session.scalar(select(func.count()).select_from(ApiToken).where(condition)) or 0
    scopes = ApiToken.scopes
    globals_ = scopes["global"]
    projects = case(
        (func.jsonb_typeof(scopes["projects"]) == "object", scopes["projects"]),
        else_=literal({}, type_=JSONB),
    )
    project_keys = func.jsonb_object_keys(projects).table_valued("value")
    project_count = (
        select(func.count()).select_from(project_keys).correlate(ApiToken).scalar_subquery()
    )
    rows = await session.execute(
        select(
            ApiToken.id,
            ApiToken.name,
            ApiToken.prefix_display,
            ApiToken.created_at,
            ApiToken.expires_at,
            ApiToken.last_used_at,
            (scopes.is_not(None) & (func.jsonb_typeof(scopes) != "null")).label("restricted"),
            case(
                (func.jsonb_typeof(globals_) == "array", func.jsonb_array_length(globals_)), else_=0
            ).label("global_count"),
            project_count.label("project_count"),
        )
        .where(condition)
        .order_by(ApiToken.created_at, ApiToken.id)
        .limit(limit)
        .offset(offset)
    )
    return [ServiceKeySummaryRead.model_validate(row) for row in rows.mappings()], total
