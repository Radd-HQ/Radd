"""Wiki space windows, permission summary and direct slug/ID lookup."""

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import ilike_term
from radd.exceptions import NotFoundError
from radd.modules.auth.models import User
from radd.modules.auth.types import Permission
from . import access, spaces
from .models import PageSpace
from .schemas import PageSpaceRead, PageSpaceSummaryRead
from .types import PageEntity


async def summary(session: AsyncSession, actor: User) -> PageSpaceSummaryRead:
    readable = await access.readable_spaces(session, actor)
    return PageSpaceSummaryRead(
        total=len(readable),
        permissions=sorted({str(permission) for held in readable.values() for permission in held}),
    )


async def page(
    session: AsyncSession,
    actor: User,
    *,
    q: str = "",
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[PageSpaceRead], int]:
    readable = await access.readable_spaces(session, actor)
    query = select(PageSpace).where(PageSpace.id.in_(readable))
    if q.strip():
        term = ilike_term(q.strip())
        query = query.where(or_(PageSpace.name.ilike(term), PageSpace.slug.ilike(term)))
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    query = query.order_by(PageSpace.position, PageSpace.name, PageSpace.id).offset(offset)
    if limit is not None:
        query = query.limit(limit)
    rows = list((await session.scalars(query)).all())
    reads = await spaces.read_spaces(session, rows)
    for row in reads:
        row.permissions = sorted(str(permission) for permission in readable[row.id])
    return reads, total or 0


async def by_identity(session: AsyncSession, actor: User, identifier: str) -> PageSpaceRead:
    space = await spaces.by_slug_or_id(session, identifier)
    held = await access.space_permissions(session, actor, space.id)
    if Permission.PAGE_READ not in held:
        # A direct lookup should not distinguish an unreadable space from an
        # absent one. A public space is readable here like any other (spec 121).
        raise NotFoundError(PageEntity.SPACE, identifier)
    row = (await spaces.read_spaces(session, [space]))[0]
    row.permissions = sorted(str(permission) for permission in held)
    return row
