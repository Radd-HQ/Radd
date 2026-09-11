"""Permission-filtered wiki space choices, without page counts or content."""

from sqlalchemy import String, cast, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.choices import ChoiceRead, page
from radd.modules.auth.models import User
from . import access
from .models import PageSpace


async def list_options(
    session: AsyncSession,
    actor: User,
    *,
    q: str = "",
    limit: int = 50,
    offset: int = 0,
    value: str | None = None,
    exclude: list[str] | None = None,
) -> tuple[list[ChoiceRead], int]:
    readable = await access.readable_spaces(session, actor)
    projection = select(
        cast(PageSpace.id, String).label("value"),
        PageSpace.name.label("label"),
        PageSpace.slug.label("hint"),
    ).where(PageSpace.id.in_(readable))
    return await page(session, projection, q=q, limit=limit, offset=offset, value=value, exclude=exclude)
