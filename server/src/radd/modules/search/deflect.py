"""KB deflection (spec 66): "does this already have an answer?" for a
half-typed issue title — top wiki pages via the docs FTS seam + top RESOLVED
items (the item FTS filtered to done/canceled state categories through the
workflow seam).

docs is a DEFERRED, feature-detected import (it loads after search in
RADD_MODULES; disabled = the docs half is empty). Both halves are FTS fused
with semantic candidates when the ai module is up (specs 103/106) and degrade
to plain FTS on any failure; the endpoint's shape won't change.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.modules.items.models import WorkItem
from radd.modules.workflow import service as workflow
from radd.modules.workflow.types import StateCategory
from radd.modules.projects.models import Project

from .models import SearchIndexRow
from .schemas import DeflectDoc, DeflectItem
from .service import build_tsquery
from .types import DEFLECT_LIMIT, SEARCH_TS_CONFIG

DOCS_MODULE = "radd.modules.pages"

# An item counts as "previously resolved" in these state categories.
RESOLVED_CATEGORIES = (StateCategory.DONE, StateCategory.CANCELED)


async def deflect_docs(session: AsyncSession, q: str) -> list[DeflectDoc]:
    """Top wiki pages: docs FTS fused with semantic candidates when available
    (spec 103) — KB questions rarely reuse the answer's exact words. Empty when
    docs is disabled; plain FTS when semantic isn't configured."""
    if DOCS_MODULE not in settings.modules:
        return []
    from radd.modules.pages import search as docs_search, spaces as docs_spaces

    results = await docs_search.search_pages(session, q, limit=DEFLECT_LIMIT)
    ordered_ids = [result.page_id for result in results]
    by_id = {result.page_id: result for result in results}
    semantic_ids = await _semantic_doc_ids(session, q)
    if semantic_ids:
        from . import fusion

        fused = fusion.rrf_fuse([ordered_ids, semantic_ids])
        missing = [page_id for page_id, _ in fused if page_id not in by_id]
        for page in await docs_search.pages_by_ids(session, missing):
            by_id[page.page_id] = page
        ordered_ids = [page_id for page_id, _ in fused if page_id in by_id]
    if not ordered_ids:
        return []
    space_names = {
        space.id: space.name for space in await docs_spaces.list_spaces(session)
    }
    return [
        DeflectDoc(
            id=page_id,
            space_id=by_id[page_id].space_id,
            title=by_id[page_id].title,
            space_name=space_names.get(by_id[page_id].space_id, ""),
        )
        for page_id in ordered_ids[:DEFLECT_LIMIT]
    ]


async def _semantic_doc_ids(session: AsyncSession, q: str) -> list[uuid.UUID]:
    """Semantic doc candidates via the ai seam (deferred; [] on any failure)."""
    from .types import AI_EMBEDDINGS_MODULE

    if AI_EMBEDDINGS_MODULE not in settings.modules:
        return []
    try:
        from radd.modules.ai.embeddings import candidates

        if not await candidates.semantic_enabled(session):
            return []
        ranked = await candidates.doc_candidates(
            session, q, public_only=False, limit=DEFLECT_LIMIT * 2
        )
    except Exception:  # noqa: BLE001 — deflection degrades to FTS, never 500s
        return []
    return [page_id for page_id, _ in ranked]


async def deflect_items(
    session: AsyncSession, project: Project, q: str
) -> list[DeflectItem]:
    """Top RESOLVED items in the project: the item FTS fused with semantic
    candidates when available (spec 106) — mirror of the docs half. Semantic
    additions re-pass the resolved-state filter: nearest-neighbour has no
    notion of state, and an OPEN lookalike is a duplicate, not an answer."""
    resolved_state_ids: list[uuid.UUID] = []
    for category in RESOLVED_CATEGORIES:
        resolved_state_ids += await workflow.state_ids_in_category(session, project.id, category)
    if not resolved_state_ids:
        return []
    rows = await _fts_resolved_rows(session, project, q, resolved_state_ids)
    ordered_ids = [row.item_id for row in rows]
    by_id = {row.item_id: row for row in rows}
    semantic_ids = await _semantic_item_ids(session, project, q)
    if semantic_ids:
        from . import fusion

        fused = fusion.rrf_fuse([ordered_ids, semantic_ids])
        missing = [item_id for item_id, _ in fused if item_id not in by_id]
        for row in await _resolved_rows_by_ids(session, project, missing, resolved_state_ids):
            by_id[row.item_id] = row
        ordered_ids = [item_id for item_id, _ in fused if item_id in by_id]
    return [
        DeflectItem(key=by_id[item_id].key, title=by_id[item_id].title)
        for item_id in ordered_ids[:DEFLECT_LIMIT]
    ]


async def _fts_resolved_rows(
    session: AsyncSession,
    project: Project,
    q: str,
    resolved_state_ids: list[uuid.UUID],
) -> list[SearchIndexRow]:
    tsquery_text = build_tsquery(q)
    if not tsquery_text:
        return []
    tsquery = func.to_tsquery(SEARCH_TS_CONFIG, tsquery_text)
    stmt = (
        select(SearchIndexRow)
        .join(WorkItem, WorkItem.id == SearchIndexRow.item_id)
        .where(
            SearchIndexRow.project_id == project.id,
            WorkItem.state_id.in_(resolved_state_ids),
            SearchIndexRow.tsv.op("@@")(tsquery),
        )
        .order_by(
            func.ts_rank_cd(SearchIndexRow.tsv, tsquery).desc(),
            SearchIndexRow.updated_at.desc(),
        )
        .limit(DEFLECT_LIMIT)
    )
    return list((await session.execute(stmt)).scalars())


async def _resolved_rows_by_ids(
    session: AsyncSession,
    project: Project,
    item_ids: list[uuid.UUID],
    resolved_state_ids: list[uuid.UUID],
) -> list[SearchIndexRow]:
    """Index rows for semantic-only candidates — the same project + resolved
    filters as the FTS statement, so fusion can't smuggle in an open item."""
    if not item_ids:
        return []
    stmt = (
        select(SearchIndexRow)
        .join(WorkItem, WorkItem.id == SearchIndexRow.item_id)
        .where(
            SearchIndexRow.item_id.in_(item_ids),
            SearchIndexRow.project_id == project.id,
            WorkItem.state_id.in_(resolved_state_ids),
        )
    )
    return list((await session.execute(stmt)).scalars())


async def _semantic_item_ids(
    session: AsyncSession, project: Project, q: str
) -> list[uuid.UUID]:
    """Semantic item candidates via the ai seam (deferred; [] on any failure)."""
    from .types import AI_EMBEDDINGS_MODULE

    if AI_EMBEDDINGS_MODULE not in settings.modules:
        return []
    try:
        from radd.modules.ai.embeddings import candidates

        if not await candidates.semantic_enabled(session):
            return []
        ranked = await candidates.item_candidates(
            session, q, project_ids=[project.id], limit=DEFLECT_LIMIT * 2
        )
    except Exception:  # noqa: BLE001 — deflection degrades to FTS, never 500s
        return []
    return [item_id for item_id, _ in ranked]
