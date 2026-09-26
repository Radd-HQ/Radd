"""KB deflection (spec 66): "does this already have an answer?" for a
half-typed issue title — top DOCUMENTS from whichever plugin provides them
(the SEARCH_DOCUMENTS socket; `pages` answers with wiki pages) + top RESOLVED
items (the item FTS filtered to done/canceled state categories through the
workflow seam).

Both halves are FTS fused with semantic candidates when a SEMANTIC_CANDIDATES
provider is live (specs 103/106, RADD-1384) and degrade to plain FTS on any
failure; with no document provider the docs half is empty. The endpoint's
shape won't change.
"""

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.items.enums import ItemEntity
from radd.modules.items.models import WorkItem
from radd.modules.workflow import service as workflow
from radd.modules.workflow.types import StateCategory
from radd.modules.projects.models import Project

from . import fusion, sources
from .models import SearchIndexRow
from .schemas import DeflectDoc, DeflectItem
from .service import build_tsquery
from .types import DEFLECT_LIMIT, SEARCH_TS_CONFIG

logger = logging.getLogger(__name__)

# An item counts as "previously resolved" in these state categories.
RESOLVED_CATEGORIES = (StateCategory.DONE, StateCategory.CANCELED)


async def deflect_docs(session: AsyncSession, q: str, *, actor) -> list[DeflectDoc]:
    """Top documents `actor` may open: each provider's FTS fused with its
    semantic candidates (spec 103) — KB questions rarely reuse the answer's
    exact words. The provider gates both halves (RADD-791's readable spaces,
    RADD-792's restricted pages), because deflection is the one page surface an
    ISSUE reader reaches. A provider that raises is skipped, never a 500."""
    providers = sources.document_sources()
    if not providers:
        return []
    live = await sources.semantic_sources(session)
    docs: list[DeflectDoc] = []
    for source in providers:
        if len(docs) >= DEFLECT_LIMIT:
            break
        try:
            hits = await _fused_documents(session, source, q, actor, live)
        except Exception:  # noqa: BLE001 — one source's failure must not blank the panel
            logger.exception("deflect: %s documents failed", source.entity_type)
            continue
        docs += [
            DeflectDoc(id=hit.id, space_id=hit.space_id, title=hit.title, space_name=hit.space_name)
            for hit in hits
        ]
    return docs[:DEFLECT_LIMIT]


async def _fused_documents(session, source, q, actor, live) -> list[sources.DocumentHit]:
    hits = await source.search(session, actor, q, limit=DEFLECT_LIMIT)
    by_id = {hit.id: hit for hit in hits}
    ordered_ids = [hit.id for hit in hits]
    rankings = await sources.semantic_rankings(
        session, live, source.entity_type, q, limit=DEFLECT_LIMIT * 2
    )
    if rankings:
        fused = fusion.rrf_fuse([ordered_ids, *sources.ids_of(rankings)])
        missing = [doc_id for doc_id, _ in fused if doc_id not in by_id]
        if missing:
            for hit in await source.resolve(session, actor, missing):
                by_id[hit.id] = hit
        ordered_ids = [doc_id for doc_id, _ in fused if doc_id in by_id]
    return [by_id[doc_id] for doc_id in ordered_ids]


async def deflect_items(
    session: AsyncSession, project: Project, q: str, *, actor=None
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
    # RADD-817: a relation-scoped reader deflects only onto rows they may see.
    if actor is not None:
        from radd.modules.auth import authz
        from radd.modules.items.service.visibility import relation_read_clause

        permissions = await authz.effective_permissions(session, actor, project=project)
        clause = await relation_read_clause(session, actor, {project.id: permissions})
        if clause is not None:
            visible = set(
                (
                    await session.execute(
                        select(WorkItem.id).where(
                            WorkItem.id.in_([row.item_id for row in rows]), clause
                        )
                    )
                ).scalars()
            )
            rows = [row for row in rows if row.item_id in visible]
    ordered_ids = [row.item_id for row in rows]
    by_id = {row.item_id: row for row in rows}
    semantic_ids = await _semantic_item_ids(session, project, q)
    if semantic_ids:
        fused = fusion.rrf_fuse([ordered_ids, *semantic_ids])
        missing = [item_id for item_id, _ in fused if item_id not in by_id]
        for row in await _resolved_rows_by_ids(session, project, missing, resolved_state_ids):
            by_id[row.item_id] = row
        ordered_ids = [item_id for item_id, _ in fused if item_id in by_id]
    if actor is not None and ordered_ids:
        from radd.modules.auth import authz
        from radd.modules.items.service.visibility import relation_read_clause
        held = await authz.effective_permissions(session, actor, project=project)
        clause = await relation_read_clause(session, actor, {project.id: held})
        stmt = select(WorkItem.id).where(WorkItem.id.in_(ordered_ids))
        if clause is not None:
            stmt = stmt.where(clause)
        allowed = set((await session.scalars(stmt)).all())
        ordered_ids = [item_id for item_id in ordered_ids if item_id in allowed]
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
) -> list[list[uuid.UUID]]:
    """Each live semantic provider's item ranking in this project (RADD-1384:
    the SEMANTIC_CANDIDATES socket; [] on any failure)."""
    live = await sources.semantic_sources(session)
    if not live:
        return []
    rankings = await sources.semantic_rankings(
        session, live, ItemEntity.ITEM, q, limit=DEFLECT_LIMIT * 2, project_ids=[project.id]
    )
    return sources.ids_of(rankings)
