"""Page templates (RADD-712). Exactly three placeholders — `{{title}}`,
`{{date}}`, `{{author}}` — because more is a template LANGUAGE. An unknown
placeholder is left alone: `{{customer}}` is an instruction to whoever fills it
in."""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import NotFoundError

from .models import PageTemplate
from .types import PageEntity

_PLACEHOLDER = re.compile(r"\{\{\s*(title|date|author)\s*\}\}")


def render(body: str, *, title: str, author: str, today: date | None = None) -> str:
    """Substitute the three placeholders. Unknown ones survive untouched."""
    values = {
        "title": title,
        "date": (today or date.today()).isoformat(),
        "author": author,
    }
    return _PLACEHOLDER.sub(lambda match: values[match.group(1)], body)


async def list_templates(
    session: AsyncSession,
    space_id: uuid.UUID | None = None,
    *,
    readable_space_ids: Iterable[uuid.UUID] | None = None,
) -> list[PageTemplate]:
    """Templates usable in a space: its own, plus the global ones."""
    query = select(PageTemplate).order_by(PageTemplate.name)
    if space_id is not None:
        query = query.where(
            (PageTemplate.space_id == space_id) | (PageTemplate.space_id.is_(None))
        )
    elif readable_space_ids is not None:
        query = query.where(
            PageTemplate.space_id.in_(set(readable_space_ids)) | PageTemplate.space_id.is_(None)
        )
    return list((await session.execute(query)).scalars())


async def by_name(
    session: AsyncSession, name: str, *, space_id: uuid.UUID | None = None
) -> PageTemplate:
    query = select(PageTemplate).where(PageTemplate.name == name)
    if space_id is not None:
        query = query.where((PageTemplate.space_id == space_id) | PageTemplate.space_id.is_(None))
    row = await session.execute(query)
    template = row.scalar_one_or_none()
    if template is None:
        raise NotFoundError(PageEntity.PAGE, f"template {name!r}")
    return template
