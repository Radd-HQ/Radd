"""Pure meaning-based retrieval (spec 103): the palette's Ask mode.

Unlike hybrid /search (which ANDs keywords and fuses), this runs the query as
ONE semantic probe over items and docs — "issues where the render farm ran out
of disk" works as a sentence. Returns `enabled: false` (never an error) when
semantic search is off, so the UI can gate without a second status call.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.modules.auth import authz
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User

from .models import SearchIndexRow
from .schemas import SemanticDoc, SemanticItem, SemanticResponse
from .service import _readable_project_ids
from .types import AI_EMBEDDINGS_MODULE

logger = logging.getLogger(__name__)

_ASK_LIMIT = 12


async def semantic_search(session: AsyncSession, user: User, q: str) -> SemanticResponse:
    q = q.strip()
    if not q or AI_EMBEDDINGS_MODULE not in settings.modules:
        return SemanticResponse(enabled=False, items=[], docs=[])
    from radd.modules.ai.embeddings import candidates

    try:
        if not await candidates.semantic_enabled(session):
            return SemanticResponse(enabled=False, items=[], docs=[])
        items = await _items(session, user, q, candidates)
        docs = await _docs(session, user, q, candidates)
    except Exception:  # noqa: BLE001 — Ask mode degrades to empty, never a 500
        logger.warning("semantic search failed", exc_info=True)
        return SemanticResponse(enabled=True, items=[], docs=[])
    return SemanticResponse(enabled=True, items=items, docs=docs)


async def _items(session: AsyncSession, user: User, q: str, candidates) -> list[SemanticItem]:
    readable = await _readable_project_ids(session, user)
    if not readable:
        return []
    ranked = await candidates.item_candidates(
        session, q, project_ids=list(readable), limit=_ASK_LIMIT
    )
    if not ranked:
        return []
    rows = {
        row.item_id: row
        for row in (
            await session.execute(
                select(SearchIndexRow).where(
                    SearchIndexRow.item_id.in_([item_id for item_id, _ in ranked])
                )
            )
        ).scalars()
    }
    results: list[SemanticItem] = []
    for item_id, distance in ranked:
        row = rows.get(item_id)
        if row is None:
            continue
        results.append(
            SemanticItem(
                item_id=row.item_id,
                project_id=row.project_id,
                key=row.key,
                title=row.title,
                score=round(max(0.0, 1.0 - distance), 3),
            )
        )
    return results


async def _docs(session: AsyncSession, user: User, q: str, candidates) -> list[SemanticDoc]:
    perms = await authz.effective_permissions(session, user)
    if Permission.PAGE_READ not in perms:
        return []
    ranked = await candidates.doc_candidates(session, q, public_only=False, limit=_ASK_LIMIT)
    if not ranked:
        return []
    from radd.modules.pages.models import Page

    pages = {
        page.id: page
        for page in (
            await session.execute(
                select(Page).where(Page.id.in_([page_id for page_id, _ in ranked]))
            )
        ).scalars()
    }
    results: list[SemanticDoc] = []
    for page_id, distance in ranked:
        page = pages.get(page_id)
        if page is None or page.archived_at is not None:
            continue
        results.append(
            SemanticDoc(
                page_id=page.id,
                space_id=page.space_id,
                title=page.title,
                score=round(max(0.0, 1.0 - distance), 3),
            )
        )
    return results
