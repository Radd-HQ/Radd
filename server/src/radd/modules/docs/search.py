"""Live FTS over doc pages (spec 43).

No outbox indexer: the corpus is written only through this module, so querying
the live rows via the migration's expression GIN index —
to_tsvector('english', title || ' ' || body) — is simpler and always fresh.
"""

import uuid

from sqlalchemy import func, literal, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .core import build_tsquery
from .models import DocPage, DocSpace
from .schemas import DocSearchResult
from .types import DOCS_TS_CONFIG, MAX_QUERY_CHARS


async def search_pages(
    session: AsyncSession,
    q: str,
    *,
    limit: int = 20,
    public_only: bool = False,
    space_id: uuid.UUID | None = None,
) -> list[DocSearchResult]:
    """Ranked live FTS over non-archived pages (docs are global — spec 86). The
    public KB (spec 74) passes `public_only=True` (PUBLIC spaces only) and
    optionally pins one space — same statement, same tsvector expression, same
    GIN index."""
    q = q.strip()[:MAX_QUERY_CHARS]
    tsquery_text = build_tsquery(q)
    if not tsquery_text:
        return []
    tsquery = func.to_tsquery(DOCS_TS_CONFIG, tsquery_text)
    # The concatenation MUST mirror the index expression for the GIN scan.
    document = DocPage.title + literal(" ") + DocPage.body
    tsv = func.to_tsvector(DOCS_TS_CONFIG, document)
    snippet = func.ts_headline(
        DOCS_TS_CONFIG,
        document,
        tsquery,
        text("'MaxWords=18, MinWords=6, MaxFragments=1'"),
    )
    stmt = (
        select(DocPage, snippet)
        .join(DocSpace, DocSpace.id == DocPage.space_id)
        .where(DocPage.archived_at.is_(None), tsv.op("@@")(tsquery))
        .order_by(func.ts_rank_cd(tsv, tsquery).desc(), DocPage.updated_at.desc())
        .limit(limit)
    )
    if public_only:
        stmt = stmt.where(DocSpace.public.is_(True))
    if space_id is not None:
        stmt = stmt.where(DocPage.space_id == space_id)
    return [
        DocSearchResult(
            page_id=page.id, space_id=page.space_id, title=page.title, snippet=headline
        )
        for page, headline in (await session.execute(stmt)).all()
    ]


async def pages_by_ids(
    session: AsyncSession, page_ids: list[uuid.UUID], *, public_only: bool = False
) -> list[DocSearchResult]:
    """Non-archived pages by id, result-shaped (spec 103: deflection fuses
    semantic candidates that FTS never surfaced, so it needs their titles).
    `public_only` re-checks the LIVE space flag (spec 106): the vector store
    carries a public flag copied at embed time, and the anonymous surface must
    not trust it for a space flipped private since."""
    if not page_ids:
        return []
    stmt = select(DocPage).where(DocPage.id.in_(page_ids), DocPage.archived_at.is_(None))
    if public_only:
        stmt = stmt.join(DocSpace, DocSpace.id == DocPage.space_id).where(
            DocSpace.public.is_(True)
        )
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
) -> list[tuple[uuid.UUID, bool, str, str]]:
    """(page_id, space_is_public, title, body) for the semantic embedder —
    non-archived pages only. `missing_from` = the embedder's (table, model)
    anti-join for the reconcile sweep, run here so each module queries only its
    own table shape (the mirror of search.rows_for_embedding)."""
    if page_ids is not None:
        stmt = (
            select(DocPage.id, DocSpace.public, DocPage.title, DocPage.body)
            .join(DocSpace, DocSpace.id == DocPage.space_id)
            .where(DocPage.id.in_(page_ids), DocPage.archived_at.is_(None))
            .limit(limit)
        )
        return [tuple(row) for row in (await session.execute(stmt)).all()]
    if missing_from is None:
        raise ValueError("pass page_ids or missing_from")
    if not missing_from.isidentifier():
        raise ValueError(f"unusable table name: {missing_from!r}")
    result = await session.execute(
        text(
            "SELECT p.id, s.public, p.title, p.body FROM doc_pages p"
            " JOIN doc_spaces s ON s.id = p.space_id"
            f" LEFT JOIN {missing_from} e ON e.page_id = p.id AND e.model = :model"
            " WHERE p.archived_at IS NULL AND e.page_id IS NULL"
            " ORDER BY p.updated_at DESC LIMIT :limit"
        ),
        {"model": model, "limit": limit},
    )
    return [tuple(row) for row in result.all()]
