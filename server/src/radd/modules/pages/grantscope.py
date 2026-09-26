"""What auth needs to know about a SPACE-scoped role grant (RADD-892): names,
existence, reach."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.kernel import GrantScopeSpec

from . import access
from .models import PageSpace


async def space_labels(
    session: AsyncSession, space_ids: set[uuid.UUID]
) -> dict[uuid.UUID, str]:
    if not space_ids:
        return {}
    rows = await session.execute(
        select(PageSpace.id, PageSpace.name).where(PageSpace.id.in_(space_ids))
    )
    return dict(rows.all())


async def space_exists(session: AsyncSession, space_id: uuid.UUID) -> bool:
    return await session.scalar(select(PageSpace.id).where(PageSpace.id == space_id)) is not None


async def space_reach(session: AsyncSession, user) -> tuple[int, int]:
    """(spaces this person may read, spaces that exist) — for the access
    inspector's summary. Answerable only here: space readability is a per-space
    ACL, not an atom auth can union."""
    readable = len(await access.readable_spaces(session, user))
    total = (await session.scalar(select(func.count()).select_from(PageSpace))) or 0
    return readable, total


SPACE_SCOPE = GrantScopeSpec(
    key="space",
    labels=space_labels,
    exists=space_exists,
    reach=space_reach,
)
