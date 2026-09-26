"""Pages as the document source search shows beside issues (RADD-1384).

Registered on the kernel SEARCH_DOCUMENTS socket, so `search` never imports
this plugin: disabling pages withdraws the provider, and deflection and Ask
mode stop returning wiki pages whose routes are gone with it.

The READER GATE lives here once — the reader's spaces BEFORE the limit
(RADD-791: filtering afterwards lets unreadable hits eat the budget) and
per-page restriction after (RADD-792: a restricted page's TITLE is usually the
sensitive part). `GET /pages/search`, the palette's searchable, the MCP
`search_pages` tool and this source all read through `readable_results`, so no
two of them can disagree about what a person may find.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.search.sources import DocumentHit

from . import access, search, service
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
    return await service.drop_restricted_results(session, actor, results)


async def readable_by_ids(
    session: AsyncSession, actor, page_ids: Sequence[uuid.UUID]
) -> list[DocSearchResult]:
    """The live pages among `page_ids` that `actor` may read — the same gate."""
    readable = await access.readable_spaces(session, actor)
    if not readable or not page_ids:
        return []
    found = await search.pages_by_ids(session, list(page_ids), space_ids=set(readable))
    return await service.drop_restricted_results(session, actor, found)


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
