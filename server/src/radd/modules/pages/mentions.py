"""Issues a page's text mentions, kept as DERIVED `item_page_links` (RADD-943).

Reconciled wholesale from the body on every save (like `backlinks.reindex`):
removing a mention removes the link; MANUAL rows are never touched, and a key
both mentioned and manually linked stays manual; an unresolvable key is text,
not an error. No permission check — the read (`links.linked_items`) filters.
Separate from `links.py` because `links` imports `service`, which calls this.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.items import service as items_service
from radd.modules.items.mentions import parse_issue_keys

from .models import ItemPageLink, Page


async def referenced_item_ids(session: AsyncSession, body: str) -> set[uuid.UUID]:
    """The item ids `body` references, in either mention form."""
    resolved: set[uuid.UUID] = set()
    for key in parse_issue_keys(body):
        item = await items_service.find_item_by_key(session, key)
        if item is not None:
            resolved.add(item.id)
    return resolved


async def reindex(session: AsyncSession, page: Page) -> None:
    """Replace this page's derived issue links. Called from the page write path
    wherever the body changed."""
    desired = await referenced_item_ids(session, page.body)
    rows = list(
        (
            await session.execute(
                select(ItemPageLink).where(ItemPageLink.page_id == page.id)
            )
        ).scalars()
    )
    desired -= {row.item_id for row in rows if not row.derived}
    existing = {row.item_id: row for row in rows if row.derived}
    for item_id, row in existing.items():
        if item_id not in desired:
            await session.delete(row)
    for item_id in desired - set(existing):
        session.add(
            ItemPageLink(
                item_id=item_id,
                page_id=page.id,
                # The editor whose save produced the row. Nobody "made" a
                # derived link, but the column is NOT NULL and this is the
                # closest true answer.
                created_by=page.updated_by,
                derived=True,
            )
        )
    await session.flush()


async def reindex_all(session: AsyncSession) -> int:
    """Rebuild every live page's derived links — for content that bypassed the save path."""
    pages = list(
        (await session.execute(select(Page).where(Page.archived_at.is_(None)))).scalars()
    )
    for page in pages:
        await reindex(session, page)
    return len(pages)
