"""Page templates (RADD-712).

Recurring pages — runbooks, meeting notes, RFCs, postmortems — should start from
a shape rather than a blank editor or a copy-paste of last time's.

**Placeholders are three, deliberately.** `{{title}}`, `{{date}}` and
`{{author}}` cover the actual need; anything more is a template LANGUAGE, which
is a project of its own with its own escaping rules, its own errors and its own
documentation. Three substitutions need none of that.

An unknown placeholder is left alone rather than blanked: `{{customer}}` in a
template is a prompt to the person filling it in, and erasing it would delete the
instruction.
"""

from __future__ import annotations

import re
import uuid
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
    session: AsyncSession, space_id: uuid.UUID | None = None
) -> list[PageTemplate]:
    """Templates usable in a space: its own, plus the global ones."""
    query = select(PageTemplate).order_by(PageTemplate.name)
    if space_id is not None:
        query = query.where(
            (PageTemplate.space_id == space_id) | (PageTemplate.space_id.is_(None))
        )
    return list((await session.execute(query)).scalars())


async def by_name(session: AsyncSession, name: str) -> PageTemplate:
    row = await session.execute(select(PageTemplate).where(PageTemplate.name == name))
    template = row.scalar_one_or_none()
    if template is None:
        raise NotFoundError(PageEntity.PAGE, f"template {name!r}")
    return template
