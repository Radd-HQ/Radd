"""Pages as a `SearchableSpec` (RADD-1327): the live page FTS, constrained to
the reader's spaces BEFORE the limit and with restricted pages dropped — the
exact gate `GET /pages/search` applies, so the two can never disagree."""

from sqlalchemy.ext.asyncio import AsyncSession

from radd.kernel import SearchableSpec

from . import access, search, service

#: After issues in the palette.
PAGE_ORDER = 20


async def search_pages(session: AsyncSession, actor, q: str, limit: int = 10) -> list[dict]:
    readable = await access.readable_spaces(session, actor)
    if not readable:
        return []
    results = await search.search_pages(session, q, limit=limit, space_ids=set(readable))
    results = await service.drop_restricted_results(session, actor, results)
    return [
        {
            "id": str(result.page_id),
            "title": result.title,
            "url": f"/pages?pageId={result.page_id}",
            "snippet": result.snippet,
        }
        for result in results
    ]


PAGE_SEARCHABLE = SearchableSpec("page", "Pages", search_pages, order=PAGE_ORDER)
