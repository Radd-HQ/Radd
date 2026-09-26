"""Pages as the document source search shows beside issues (RADD-1384), on the
kernel SEARCH_DOCUMENTS socket, so disabling pages withdraws it.

The READER GATE lives here once — the reader's spaces BEFORE the limit
(RADD-791), per-page restriction after (RADD-792). `GET /pages/search`, the
palette, MCP `search_pages` and this source all read `readable_results`.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.search.sources import DocumentHit

from . import access, page_access, search
from .models import PageSpace
from .schemas import DocSearchResult
from .types import PageEntity


async def readable_results(
    session: AsyncSession, actor, q: str, *, limit: int
) -> list[DocSearchResult]:
    """Ranked page FTS over what `actor` may read."""
    readable = await access.readable_spaces(session, actor)
    if not readable:
        return []
    results = await search.search_pages(session, q, limit=limit, space_ids=set(readable))
    return await page_access.drop_restricted(session, actor, results, "page_id")


async def readable_by_ids(
    session: AsyncSession, actor, page_ids: Sequence[uuid.UUID]
) -> list[DocSearchResult]:
    """The live pages among `page_ids` that `actor` may read — the same gate."""
    readable = await access.readable_spaces(session, actor)
    if not readable or not page_ids:
        return []
    found = await search.pages_by_ids(session, list(page_ids), space_ids=set(readable))
    return await page_access.drop_restricted(session, actor, found, "page_id")


class PageDocuments:
    """`kernel.sockets.SearchDocumentSource` over wiki pages."""

    entity_type = PageEntity.PAGE.value

    async def search(self, session: AsyncSession, actor, q: str, *, limit: int) -> list[DocumentHit]:
        return await _hits(session, await readable_results(session, actor, q, limit=limit))

    async def resolve(
        self, session: AsyncSession, actor, ids: Sequence[uuid.UUID]
    ) -> list[DocumentHit]:
        return await _hits(session, await readable_by_ids(session, actor, ids))


async def _hits(session: AsyncSession, results: list[DocSearchResult]) -> list[DocumentHit]:
    """Result rows with their space's name — one query for the spaces named."""
    if not results:
        return []
    space_ids = {result.space_id for result in results}
    names = dict(
        (
            await session.execute(
                select(PageSpace.id, PageSpace.name).where(PageSpace.id.in_(space_ids))
            )
        ).all()
    )
    return [
        DocumentHit(
            id=result.page_id,
            space_id=result.space_id,
            title=result.title,
            space_name=names.get(result.space_id, ""),
            snippet=result.snippet,
        )
        for result in results
    ]
