"""Lean SQL choice windows; owning modules supply an authorized projection."""
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import ilike_term


class ChoiceRead(BaseModel):
    value: str
    label: str
    hint: str = ""


async def page(session: AsyncSession, projection, *, q: str = "", limit: int = 50,
               offset: int = 0, value: str | None = None, exclude: list[str] | None = None) -> tuple[list[ChoiceRead], int]:
    """Project value/label/hint only, with permission and deduplication upstream."""
    options = projection.subquery()
    query = select(options)
    if exclude:
        query = query.where(options.c.value.not_in(exclude))
    if value is not None:
        query = query.where(options.c.value == value)
    if q.strip():
        term = ilike_term(q.strip())
        query = query.where(or_(options.c.value.ilike(term), options.c.label.ilike(term), options.c.hint.ilike(term)))
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await session.execute(query.order_by(options.c.label, options.c.hint, options.c.value)
                                  .limit(limit).offset(offset))).mappings()
    return [ChoiceRead.model_validate(row) for row in rows], total or 0
