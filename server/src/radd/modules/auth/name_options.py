"""Public person references: IDs and display names, without private account fields."""

from sqlalchemy import String, case, cast, select
from sqlalchemy.ext.asyncio import AsyncSession
from radd.choices import ChoiceRead, page
from .models import User
from .types import NON_PERSON_SOURCES, UserSource


async def list_options(
    session: AsyncSession,
    *,
    q: str = "",
    limit: int = 50,
    offset: int = 0,
    value: str | None = None,
) -> tuple[list[ChoiceRead], int]:
    # Same population as the public directory: inactive and service identities
    # remain manageable, mail-provisioned requesters are not ordinary choices.
    projection = select(
        cast(User.id, String).label("value"),
        User.name.label("label"),
        case(
            (User.active.is_(False), "Inactive account"),
            (User.source == UserSource.SERVICE, "Service account"),
            else_="",
        ).label("hint"),
    ).where(User.source.notin_(NON_PERSON_SOURCES))
    return await page(session, projection, q=q, limit=limit, offset=offset, value=value)
