"""Issues as a `SearchableSpec` (RADD-1327) — the tuned item search the
palette has always used, registered through the same seam a plugin's entity
uses, so `/search/entities` lists every searchable type from one registry."""

from sqlalchemy.ext.asyncio import AsyncSession

from radd.kernel import SearchableSpec
from radd.mailrender import issue_url

from . import service

#: Issues first in the palette, before any contributed type.
ITEM_ORDER = 10


async def search_items(session: AsyncSession, actor, q: str, limit: int = 10) -> list[dict]:
    hits = await service.search(session, actor, q, limit=limit)
    return [
        {
            "id": str(hit.item_id),
            "title": hit.title,
            "subtitle": hit.key,
            "url": issue_url("", hit.key),
            "snippet": hit.snippet,
        }
        for hit in hits
    ]


ITEM_SEARCHABLE = SearchableSpec("item", "Issues", search_items, mentionable=True, order=ITEM_ORDER)
