"""pgvector schema + query primitives (spec 103).

Everything here is raw-SQL over the session — the embeddings tables are not
ORM-mapped (see the package docstring). Vectors travel as SQL literals
('[0.1,0.2,...]'), which pgvector parses natively; no client library needed.

The HNSW index is an EXPRESSION-CAST PARTIAL index per active model:
    ... USING hnsw ((embedding::halfvec(<dim>)) halfvec_cosine_ops)
    WHERE model = '<model>'
so a model swap needs no migration: `sync_index` drops the stale index and
builds the new one, and the reconcile sweep re-embeds rows whose model differs.
Queries repeat the same cast + WHERE so the planner uses the partial index.
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

ITEM_TABLE = "item_embeddings"
DOC_TABLE = "doc_embeddings"
_INDEX_NAMES = {ITEM_TABLE: "ix_item_embeddings_hnsw", DOC_TABLE: "ix_doc_embeddings_hnsw"}

# Model names land inside index predicates; keep them boring.
_MODEL_RE = re.compile(r"^[A-Za-z0-9/_.:-]{1,200}$")

_SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS {ITEM_TABLE} (
    item_id uuid PRIMARY KEY REFERENCES work_items(id) ON DELETE CASCADE,
    project_id uuid NOT NULL,
    model varchar(200) NOT NULL,
    content_hash varchar(64) NOT NULL,
    embedding halfvec NOT NULL,
    updated_at timestamp NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_item_embeddings_project_id ON {ITEM_TABLE} (project_id);
CREATE INDEX IF NOT EXISTS ix_item_embeddings_model ON {ITEM_TABLE} (model);
CREATE TABLE IF NOT EXISTS {DOC_TABLE} (
    page_id uuid PRIMARY KEY REFERENCES doc_pages(id) ON DELETE CASCADE,
    public boolean NOT NULL DEFAULT false,
    model varchar(200) NOT NULL,
    content_hash varchar(64) NOT NULL,
    embedding halfvec NOT NULL,
    updated_at timestamp NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_doc_embeddings_model ON {DOC_TABLE} (model);
"""

_available: bool | None = None  # process cache; extension presence can't change mid-run


async def vector_available(session: AsyncSession) -> bool:
    global _available
    if _available is None:
        row = await session.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        )
        _available = row.scalar() is not None
    return _available


def reset_availability_cache() -> None:  # test seam
    global _available
    _available = None


async def ensure_schema(session: AsyncSession) -> bool:
    """Create the embeddings tables when the extension exists (idempotent).
    Returns availability, so the startup hook doubles as the gate check."""
    if not await vector_available(session):
        return False
    for statement in _SCHEMA_SQL.strip().split(";"):
        if statement.strip():
            await session.execute(text(statement))
    return True


def vector_literal(values: Sequence[float]) -> str:
    """A pgvector input literal. Values come from our own embed() call, but keep
    the formatting strict-numeric anyway."""
    return "[" + ",".join(f"{float(v):.8g}" for v in values) + "]"


def _validated(model: str, dim: int) -> tuple[str, int]:
    if not _MODEL_RE.match(model):
        raise ValueError(f"unusable embedding model name: {model!r}")
    if not (1 <= int(dim) <= 16000):
        raise ValueError(f"unusable embedding dimension: {dim!r}")
    return model, int(dim)


async def sync_index(session: AsyncSession, table: str, *, model: str, dim: int) -> None:
    """Make the table's HNSW index match the active model (drop stale, build
    current). Interpolation is safe: model/dim are validated, and the literal
    lands in DDL where bind parameters cannot go (typmods, predicates)."""
    model, dim = _validated(model, dim)
    index = _INDEX_NAMES[table]
    existing = await session.execute(
        text("SELECT indexdef FROM pg_indexes WHERE indexname = :name"), {"name": index}
    )
    definition = existing.scalar()
    wanted_marker = f"halfvec({dim})"
    # pg_indexes NORMALIZES the predicate ("model = 'x'" comes back as
    # "((model)::text = 'x'::text)"), so match the quoted literal, never our own
    # spelling — a false negative here is not cosmetic: it DROP+CREATEs the HNSW
    # index on every embedder batch, an O(rows) rebuild per batch (quadratic
    # over a backfill; 12s/batch by 68k rows) that also blocks writers.
    model_marker = f"'{model}'"
    if definition and wanted_marker in definition and model_marker in definition:
        return
    if definition:
        await session.execute(text(f"DROP INDEX {index}"))
        logger.info("embeddings: rebuilding %s for model %s (%sd)", index, model, dim)
    await session.execute(
        text(
            f"CREATE INDEX {index} ON {table} "
            f"USING hnsw ((embedding::halfvec({dim})) halfvec_cosine_ops) "
            f"WHERE model = '{model}'"
        )
    )


async def upsert_item(
    session: AsyncSession,
    *,
    item_id: uuid.UUID,
    project_id: uuid.UUID,
    model: str,
    content_hash: str,
    embedding: Sequence[float],
) -> None:
    await session.execute(
        text(
            f"INSERT INTO {ITEM_TABLE} (item_id, project_id, model, content_hash, embedding)"
            " VALUES (:item_id, :project_id, :model, :hash, (:vec)::halfvec)"
            " ON CONFLICT (item_id) DO UPDATE SET project_id = :project_id,"
            " model = :model, content_hash = :hash, embedding = (:vec)::halfvec,"
            " updated_at = now()"
        ),
        {
            "item_id": item_id,
            "project_id": project_id,
            "model": model,
            "hash": content_hash,
            "vec": vector_literal(embedding),
        },
    )


async def upsert_doc(
    session: AsyncSession,
    *,
    page_id: uuid.UUID,
    public: bool,
    model: str,
    content_hash: str,
    embedding: Sequence[float],
) -> None:
    await session.execute(
        text(
            f"INSERT INTO {DOC_TABLE} (page_id, public, model, content_hash, embedding)"
            " VALUES (:page_id, :public, :model, :hash, (:vec)::halfvec)"
            " ON CONFLICT (page_id) DO UPDATE SET public = :public, model = :model,"
            " content_hash = :hash, embedding = (:vec)::halfvec, updated_at = now()"
        ),
        {
            "page_id": page_id,
            "public": public,
            "model": model,
            "hash": content_hash,
            "vec": vector_literal(embedding),
        },
    )


async def delete_item(session: AsyncSession, item_id: uuid.UUID) -> None:
    await session.execute(
        text(f"DELETE FROM {ITEM_TABLE} WHERE item_id = :id"), {"id": item_id}
    )


async def delete_doc(session: AsyncSession, page_id: uuid.UUID) -> None:
    await session.execute(text(f"DELETE FROM {DOC_TABLE} WHERE page_id = :id"), {"id": page_id})


async def item_embedding(
    session: AsyncSession, item_id: uuid.UUID, *, model: str
) -> list[float] | None:
    """The stored vector for an item under the active model (similar-issues seed)."""
    row = await session.execute(
        text(
            f"SELECT embedding::text FROM {ITEM_TABLE}"
            " WHERE item_id = :id AND model = :model"
        ),
        {"id": item_id, "model": model},
    )
    raw = row.scalar()
    if raw is None:
        return None
    return [float(v) for v in raw.strip("[]").split(",") if v]


async def nearest_items(
    session: AsyncSession,
    embedding: Sequence[float],
    *,
    model: str,
    dim: int,
    project_ids: Sequence[uuid.UUID],
    exclude_item_id: uuid.UUID | None,
    limit: int,
) -> list[tuple[uuid.UUID, float]]:
    """(item_id, cosine distance) nearest first. RBAC pre-filtered in the WHERE —
    with iterative scan the filtered HNSW walk keeps going until LIMIT is filled,
    so narrow-access users still get full result sets."""
    model, dim = _validated(model, dim)
    if not project_ids:
        return []
    await session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
    rows = await session.execute(
        text(
            f"SELECT item_id, (embedding::halfvec({dim})) <=> (:vec)::halfvec({dim}) AS distance"
            f" FROM {ITEM_TABLE}"
            f" WHERE model = :model AND project_id = ANY(:projects)"
            "  AND (:exclude)::uuid IS DISTINCT FROM item_id"
            " ORDER BY distance LIMIT :limit"
        ),
        {
            "vec": vector_literal(embedding),
            "model": model,
            "projects": list(project_ids),
            "exclude": exclude_item_id,
            "limit": limit,
        },
    )
    return [(item_id, float(distance)) for item_id, distance in rows.all()]


async def nearest_docs(
    session: AsyncSession,
    embedding: Sequence[float],
    *,
    model: str,
    dim: int,
    public_only: bool,
    limit: int,
) -> list[tuple[uuid.UUID, float]]:
    model, dim = _validated(model, dim)
    await session.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))
    rows = await session.execute(
        text(
            f"SELECT page_id, (embedding::halfvec({dim})) <=> (:vec)::halfvec({dim}) AS distance"
            f" FROM {DOC_TABLE}"
            " WHERE model = :model AND (NOT :public_only OR public)"
            " ORDER BY distance LIMIT :limit"
        ),
        {
            "vec": vector_literal(embedding),
            "model": model,
            "public_only": public_only,
            "limit": limit,
        },
    )
    return [(page_id, float(distance)) for page_id, distance in rows.all()]


async def coverage(session: AsyncSession, *, model: str) -> dict[str, int]:
    """Counts for Settings → AI ("2,314 / 2,400 items embedded")."""
    items_total = (await session.execute(text("SELECT count(*) FROM search_index"))).scalar()
    items_done = (
        await session.execute(
            text(f"SELECT count(*) FROM {ITEM_TABLE} WHERE model = :m"), {"m": model}
        )
    ).scalar()
    docs_total = (
        await session.execute(
            text("SELECT count(*) FROM doc_pages WHERE archived_at IS NULL")
        )
    ).scalar()
    docs_done = (
        await session.execute(
            text(f"SELECT count(*) FROM {DOC_TABLE} WHERE model = :m"), {"m": model}
        )
    ).scalar()
    return {
        "items_total": int(items_total or 0),
        "items_embedded": int(items_done or 0),
        "docs_total": int(docs_total or 0),
        "docs_embedded": int(docs_done or 0),
    }
