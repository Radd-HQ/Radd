"""Directory-group references without membership or graph hydration."""

from sqlalchemy import String, cast, select
from sqlalchemy.ext.asyncio import AsyncSession
from radd.choices import ChoiceRead, page
from radd.modules.auth import authz
from radd.modules.auth.models import User
from .models import Group


async def list_options(
    session: AsyncSession,
    actor: User,
    *,
    q: str = "",
    limit: int = 50,
    offset: int = 0,
    value: str | None = None,
) -> tuple[list[ChoiceRead], int]:
    await authz.require_member(session, actor)
    projection = select(
        cast(Group.id, String).label("value"), Group.name.label("label"), Group.dn.label("hint")
    )
    return await page(session, projection, q=q, limit=limit, offset=offset, value=value)
