"""Lean template windows; fetch markdown only for a directly opened template."""

import uuid

from sqlalchemy import false, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import ilike_term
from radd.exceptions import NotFoundError
from radd.modules.auth.models import User
from . import access
from .models import PageSpace, PageTemplate
from .schemas import PageTemplateRead, PageTemplateSummaryRead
from .types import PageEntity


async def _visible(session: AsyncSession, actor: User):
    readable = await access.readable_spaces(session, actor)
    # Match the complete template endpoint: no readable spaces means no templates.
    return or_(PageTemplate.space_id.is_(None), PageTemplate.space_id.in_(readable)) if readable else false()


async def page(session: AsyncSession, actor: User, *, q: str = "", limit: int = 50,
               offset: int = 0) -> tuple[list[PageTemplateSummaryRead], int]:
    condition = await _visible(session, actor)
    if q.strip():
        term = ilike_term(q.strip())
        condition &= or_(PageTemplate.name.ilike(term), PageTemplate.description.ilike(term))
    total = await session.scalar(select(func.count()).select_from(PageTemplate).where(condition))
    query = (
        select(PageTemplate.id, PageTemplate.name, PageTemplate.description, PageTemplate.icon,
               PageTemplate.space_id, PageSpace.name.label("space_name"))
        .outerjoin(PageSpace, PageTemplate.space_id == PageSpace.id)
        .where(condition).order_by(PageTemplate.name, PageTemplate.id).limit(limit).offset(offset)
    )
    rows = (await session.execute(query)).mappings()
    return [PageTemplateSummaryRead.model_validate(row) for row in rows], total or 0


async def by_id(session: AsyncSession, actor: User, template_id: uuid.UUID) -> PageTemplateRead:
    row = await session.scalar(select(PageTemplate).where(PageTemplate.id == template_id, await _visible(session, actor)))
    if row is None:
        raise NotFoundError(PageEntity.PAGE, template_id)
    return PageTemplateRead.model_validate(row)
