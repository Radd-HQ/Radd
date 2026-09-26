"""Pages as a `SearchableSpec` (RADD-1327): the live page FTS, constrained to
the reader's spaces BEFORE the limit and with restricted pages dropped — the
one gate (`search_source.readable_results`) every page search reads."""

from sqlalchemy.ext.asyncio import AsyncSession

from radd.kernel import SearchableSpec

from .search_source import readable_results

#: After issues in the palette.
PAGE_ORDER = 20


async def search_pages(session: AsyncSession, actor, q: str, limit: int = 10) -> list[dict]:
    results = await readable_results(session, actor, q, limit=limit)
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
