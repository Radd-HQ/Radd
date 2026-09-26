"""Live FTS over pages (spec 43).

No outbox indexer: the corpus is written only through this module, so querying
the live rows via the migration's expression GIN index —
to_tsvector('english', title || ' ' || body) — is simpler and always fresh.
"""

import uuid

from sqlalchemy import func, literal, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.search.service import build_tsquery
from radd.modules.search.types import MAX_QUERY_CHARS

from .models import Page, PageSpace
from .schemas import DocSearchResult
from .types import DOCS_TS_CONFIG


async def search_pages(
    session: AsyncSession,
    q: str,
    *,
    limit: int = 20,
    space_id: uuid.UUID | None = None,
    space_ids: "set[uuid.UUID] | None" = None,
) -> list[DocSearchResult]:
    """Ranked live FTS over non-archived pages, constrained to `space_ids` BEFORE
    the limit (RADD-791)."""
    q = q.strip()[:MAX_QUERY_CHARS]
    tsquery_text = build_tsquery(q)
    if not tsquery_text:
        return []
    tsquery = func.to_tsquery(DOCS_TS_CONFIG, tsquery_text)
    # The concatenation MUST mirror the index expression for the GIN scan.
    document = Page.title + literal(" ") + Page.body
    tsv = func.to_tsvector(DOCS_TS_CONFIG, document)
    snippet = func.ts_headline(
        DOCS_TS_CONFIG,
        document,
        tsquery,
        text("'MaxWords=18, MinWords=6, MaxFragments=1'"),
    )
    stmt = (
        select(Page, snippet)
        .join(PageSpace, PageSpace.id == Page.space_id)
        .where(Page.archived_at.is_(None), tsv.op("@@")(tsquery))
        .order_by(func.ts_rank_cd(tsv, tsquery).desc(), Page.updated_at.desc())
        .limit(limit)
    )
    if space_id is not None:
        stmt = stmt.where(Page.space_id == space_id)
    # BEFORE the limit: filtering afterwards lets unreadable hits eat the budget.
    if space_ids is not None:
        stmt = stmt.where(Page.space_id.in_(space_ids))
    return [
        DocSearchResult(
            page_id=page.id, space_id=page.space_id, title=page.title, snippet=headline
        )
        for page, headline in (await session.execute(stmt)).all()
    ]


async def pages_by_ids(
    session: AsyncSession,
    page_ids: list[uuid.UUID],
    *,
    space_ids: "set[uuid.UUID] | None" = None,
) -> list[DocSearchResult]:
    """Non-archived pages by id, result-shaped (semantic candidates FTS never
    surfaced), constrained to `space_ids`."""
    if not page_ids:
        return []
    stmt = select(Page).where(Page.id.in_(page_ids), Page.archived_at.is_(None))
    if space_ids is not None:
        stmt = stmt.where(Page.space_id.in_(space_ids))
    return [
        DocSearchResult(page_id=page.id, space_id=page.space_id, title=page.title, snippet="")
        for page in (await session.execute(stmt)).scalars()
    ]


# --- the ai-embedder seam (spec 103) ------------------------------------------


async def pages_for_embedding(
    session: AsyncSession,
    *,
    page_ids: list[uuid.UUID] | None = None,
    missing_from: str | None = None,
    model: str = "",
    limit: int = 200,
) -> list[tuple[uuid.UUID, str, str]]:
    """(page_id, title, body) for the semantic embedder —
    non-archived pages only. `missing_from` = the embedder's (table, model)
    anti-join for the reconcile sweep, run here so each module queries only its
    own table shape (the mirror of search.rows_for_embedding)."""
    if page_ids is not None:
        stmt = (
            select(Page.id, Page.title, Page.body)
            .where(Page.id.in_(page_ids), Page.archived_at.is_(None))
            .limit(limit)
        )
        return [tuple(row) for row in (await session.execute(stmt)).all()]
    if missing_from is None:
        raise ValueError("pass page_ids or missing_from")
    if not missing_from.isidentifier():
        raise ValueError(f"unusable table name: {missing_from!r}")
    result = await session.execute(
        text(
            "SELECT p.id, p.title, p.body FROM pages p"
            f" LEFT JOIN {missing_from} e ON e.page_id = p.id AND e.model = :model"
            " WHERE p.archived_at IS NULL AND e.page_id IS NULL"
            " ORDER BY p.updated_at DESC LIMIT :limit"
        ),
        {"model": model, "limit": limit},
    )
    return [tuple(row) for row in result.all()]
