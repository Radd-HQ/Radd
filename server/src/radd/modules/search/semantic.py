"""Pure meaning-based retrieval (spec 103): the palette's Ask mode.

Unlike hybrid /search (which ANDs keywords and fuses), this runs the query as
ONE semantic probe over items and documents — "issues where the render farm
ran out of disk" works as a sentence. Returns `enabled: false` (never an error)
when no SEMANTIC_CANDIDATES provider is live (RADD-1384: `ai` disabled, or its
feature/role/store off), so the UI can gate without a second status call.
Documents come from whichever SEARCH_DOCUMENTS provider is loaded; none means
items alone.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth.models import User
from radd.modules.items.enums import ItemEntity

from . import sources
from .models import SearchIndexRow
from .schemas import SemanticDoc, SemanticItem, SemanticResponse
from .service import _readable_project_ids, _relation_index_clause

logger = logging.getLogger(__name__)

_ASK_LIMIT = 12


async def semantic_search(session: AsyncSession, user: User, q: str) -> SemanticResponse:
    q = q.strip()
    live = await sources.semantic_sources(session) if q else []
    if not live:
        return SemanticResponse(enabled=False, items=[], docs=[])
    try:
        items = await _items(session, user, q, live)
        docs = await _docs(session, user, q, live)
    except Exception:  # noqa: BLE001 — Ask mode degrades to empty, never a 500
        logger.warning("semantic search failed", exc_info=True)
        return SemanticResponse(enabled=True, items=[], docs=[])
    return SemanticResponse(enabled=True, items=items, docs=docs)


def _score(distance: float) -> float:
    return round(max(0.0, 1.0 - distance), 3)


async def _items(session: AsyncSession, user: User, q: str, live) -> list[SemanticItem]:
    readable = await _readable_project_ids(session, user)
    if not readable:
        return []
    ranked = sources.nearest(
        await sources.semantic_rankings(
            session, live, ItemEntity.ITEM, q, limit=_ASK_LIMIT, project_ids=list(readable)
        )
    )[:_ASK_LIMIT]
    if not ranked:
        return []
    # RADD-817: the ANN prefilter is project-level; the relation filter lands
    # here, at materialization — a semantic hit the reader may not see never
    # becomes a row.
    stmt = select(SearchIndexRow).where(
        SearchIndexRow.item_id.in_([item_id for item_id, _ in ranked])
    )
    relation_clause = await _relation_index_clause(session, user)
    if relation_clause is not None:
        stmt = stmt.where(relation_clause)
    rows = {row.item_id: row for row in (await session.execute(stmt)).scalars()}
    return [
        SemanticItem(
            item_id=row.item_id,
            project_id=row.project_id,
            key=row.key,
            title=row.title,
            score=_score(distance),
        )
        for item_id, distance in ranked
        if (row := rows.get(item_id)) is not None
    ]


async def _docs(session: AsyncSession, user: User, q: str, live) -> list[SemanticDoc]:
    """Each document provider's candidates, materialized through ITS gate
    (`resolve`: for pages the reader's spaces, RADD-791, and per-page
    restriction) — a candidate the reader may not open never becomes a row."""
    results: list[SemanticDoc] = []
    for source in sources.document_sources():
        ranked = sources.nearest(
            await sources.semantic_rankings(
                session, live, source.entity_type, q, limit=_ASK_LIMIT
            )
        )[:_ASK_LIMIT]
        if not ranked:
            continue
        hits = {
            hit.id: hit
            for hit in await source.resolve(session, user, [doc_id for doc_id, _ in ranked])
        }
        results += [
            SemanticDoc(
                page_id=hit.id, space_id=hit.space_id, title=hit.title, score=_score(distance)
            )
            for doc_id, distance in ranked
            if (hit := hits.get(doc_id)) is not None
        ]
    return results
