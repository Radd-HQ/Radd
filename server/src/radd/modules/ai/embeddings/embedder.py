"""The embedding indexer (spec 103): an outbox consumer + a reconcile sweep.

Event-driven: item/comment/doc events re-embed the affected entity. The sweep
runs on zero-event ticks and is three mechanisms in ONE query shape (an
anti-join on `model`): first-enable backfill, coverage of silent events the
head-seeded cursor skips (Jira imports reach `search_index` because the search
indexer deliberately does not skip them — the sweep sees those rows as
missing), and re-embeds after a model change. Do not "fix" the silent-skip:
the sweep converges it by design.

Hash-skip: `content_hash` (sha256 of the embed text) makes replays and no-op
edits free. A silent content change to an ALREADY-embedded row is the one gap
(documented; the next real event or model change heals it).
"""

from __future__ import annotations

import hashlib
from enum import StrEnum
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import SessionLocal
from radd.modules.events import runner
from radd.modules.events.service import Event

from .. import client, features, registry
from ..types import AiFeature, AiRole
from . import service as store

logger = logging.getLogger(__name__)

CONSUMER_NAME = "ai.embedder"

_ITEM_EVENTS = {"item.created", "item.updated"}
_COMMENT_EVENTS = {"comment.created", "comment.updated", "comment.deleted"}
_PAGE_EVENTS = {"page.created", "page.updated", "page.restored", "page.moved"}
_ITEM_DELETE = "item.deleted"
_PAGE_DELETE = "page.deleted"


class EmbedTaskKind(StrEnum):
    """What one embed task does (RADD-898) — was a comment-defined vocabulary
    compared as bare literals in five places."""

    ITEM = "item"
    DOC = "doc"
    DROP_ITEM = "drop_item"
    DROP_DOC = "drop_doc"


@dataclass(frozen=True)
class EmbedTask:
    kind: EmbedTaskKind
    entity_id: uuid.UUID


def plan_for_event(
    event_type: str, entity_id: str | None, payload: dict
) -> tuple[str, uuid.UUID | None] | None:
    """(kind, id) for an event — kind "item"/"doc"/"drop_item"/"drop_doc" (pure).

    Item/doc events carry their subject as the event's entity_id (a string
    column); comment events name the owning item in the payload.
    """
    def _coerce(raw: object) -> uuid.UUID | None:
        try:
            return uuid.UUID(str(raw)) if raw else None
        except ValueError:
            return None

    if event_type in _ITEM_EVENTS:
        return (EmbedTaskKind.ITEM, _coerce(entity_id))
    if event_type in _COMMENT_EVENTS:
        return (EmbedTaskKind.ITEM, _coerce((payload.get("item") or {}).get("id")))
    if event_type == _ITEM_DELETE:
        return (EmbedTaskKind.DROP_ITEM, _coerce(entity_id))
    if event_type in _PAGE_EVENTS:
        return (EmbedTaskKind.DOC, _coerce(entity_id))
    if event_type == _PAGE_DELETE:
        return (EmbedTaskKind.DROP_DOC, _coerce(entity_id))
    return None


def embed_text(key: str, title: str, description: str) -> str:
    """The canonical text a vector represents (pure; capped).

    Deliberately EXCLUDES comment text: an item's vector identity is its title
    + description. Imported corpora carry boilerplate comments (automation
    nags, branch/MR notifications) shared verbatim by thousands of issues, and
    embedding them made unrelated issues nearest neighbors. Comment matches
    still surface through the FTS half of every fusion. Changing this recipe
    changes every content hash, so the reconcile sweep re-embeds the corpus on
    its own — no migration, no manual backfill.
    """
    joined = "\n".join(part for part in (key, title, description) if part)
    return joined[: settings.ai_embed_max_chars]


def content_hash(text_value: str) -> str:
    return hashlib.sha256(text_value.encode()).hexdigest()


#: Why the last embedder iteration failed, or None (RADD-723). Module state
#: rather than a table: it describes THIS process's most recent attempt, and a
#: worker restart should forget it — a stale "it broke" is worse than silence.
_last_error: str | None = None


def last_error() -> str | None:
    return _last_error


async def run_once() -> int:
    """One tick: quick gates, one consumer batch, else one sweep batch."""
    async with SessionLocal() as session:
        if not await store.vector_available(session):
            return 0
        if not await features.feature_enabled(session, AiFeature.SEMANTIC_SEARCH):
            return 0
        resolved = await registry.resolve_role(session, AiRole.EMBEDDINGS)
    if resolved is None:
        return 0

    # RADD-723: remember why an iteration failed and clear it on the next
    # success, so the AI settings page can say WHY coverage is zero. The caller
    # (the task loop) still owns logging and retry; this only records.
    global _last_error
    try:
        consumed = await runner.run_head_seeded(
            CONSUMER_NAME,
            batch_size=settings.ai_embed_batch,
            plan=_plan,
            deliver=_deliver,
        )
        if consumed:
            _last_error = None
            return consumed
        swept = await _sweep()
    except Exception as exc:
        _last_error = f"{type(exc).__name__}: {exc}"
        raise
    _last_error = None
    return swept


async def _plan(session: AsyncSession, event: Event) -> EmbedTask | None:
    decision = plan_for_event(event.event_type, event.entity_id, event.payload or {})
    if decision is None:
        return None
    kind, entity_id = decision
    if entity_id is None:
        return None
    # Deletes are planning-phase writes (the runner commits them with the cursor).
    if kind == EmbedTaskKind.DROP_ITEM:
        await store.delete_item(session, entity_id)
        return None
    if kind == EmbedTaskKind.DROP_DOC:
        await store.delete_doc(session, entity_id)
        return None
    return EmbedTask(kind=kind, entity_id=entity_id)


async def _deliver(tasks: list[EmbedTask]) -> None:
    item_ids = list({t.entity_id for t in tasks if t.kind == EmbedTaskKind.ITEM})
    page_ids = list({t.entity_id for t in tasks if t.kind == EmbedTaskKind.DOC})
    async with SessionLocal() as session:
        resolved = await registry.resolve_role(session, AiRole.EMBEDDINGS)
        if resolved is None:
            return
        if item_ids:
            from radd.modules.search import service as search_service

            rows = await search_service.rows_for_embedding(session, item_ids=item_ids)
            await _embed_items(session, resolved, rows)
        if page_ids:
            from radd.modules.pages import search as docs_search

            pages = await docs_search.pages_for_embedding(session, page_ids=page_ids)
            await _embed_docs(session, resolved, pages)
        await session.commit()


async def _sweep() -> int:
    """One reconcile batch: rows missing under the active model, both tables."""
    async with SessionLocal() as session:
        resolved = await registry.resolve_role(session, AiRole.EMBEDDINGS)
        if resolved is None:
            return 0
        from radd.modules.search import service as search_service

        rows = await search_service.rows_for_embedding(
            session,
            missing_from=store.ITEM_TABLE,
            model=resolved.model,
            limit=settings.ai_embed_batch,
        )
        done = 0
        if rows:
            done += await _embed_items(session, resolved, rows)
        else:
            from radd.modules.pages import search as docs_search

            pages = await docs_search.pages_for_embedding(
                session,
                missing_from=store.PAGE_TABLE,
                model=resolved.model,
                limit=settings.ai_embed_batch,
            )
            if pages:
                done += await _embed_docs(session, resolved, pages)
        if done:
            await session.commit()
            logger.info("ai.embedder: reconcile embedded %d entities", done)
        return done


async def _embed_items(session: AsyncSession, resolved, rows) -> int:
    if not rows:
        return 0
    texts = [embed_text(r.key, r.title, r.description) for r in rows]
    hashes = [content_hash(t) for t in texts]
    fresh = await _fresh_indexes(
        session, store.ITEM_TABLE, "item_id", [r.item_id for r in rows], hashes, resolved.model
    )
    if not fresh:
        return 0
    vectors = await client.embed(
        session, AiRole.EMBEDDINGS, [texts[index] for index in fresh]
    )
    dim = len(vectors[0]) if vectors and vectors[0] else 0
    if not dim:
        return 0
    await store.sync_index(session, store.ITEM_TABLE, model=resolved.model, dim=dim)
    for position, index in enumerate(fresh):
        row = rows[index]
        await store.upsert_item(
            session,
            item_id=row.item_id,
            project_id=row.project_id,
            model=resolved.model,
            content_hash=hashes[index],
            embedding=vectors[position],
        )
    return len(fresh)


async def _embed_docs(session: AsyncSession, resolved, pages) -> int:
    if not pages:
        return 0
    texts = [embed_text("", title, body) for _, _, title, body in pages]
    hashes = [content_hash(t) for t in texts]
    fresh = await _fresh_indexes(
        session, store.PAGE_TABLE, "page_id", [p[0] for p in pages], hashes, resolved.model
    )
    if not fresh:
        return 0
    vectors = await client.embed(session, AiRole.EMBEDDINGS, [texts[i] for i in fresh])
    dim = len(vectors[0]) if vectors and vectors[0] else 0
    if not dim:
        return 0
    await store.sync_index(session, store.PAGE_TABLE, model=resolved.model, dim=dim)
    for position, index in enumerate(fresh):
        page_id, public, _, _ = pages[index]
        await store.upsert_doc(
            session,
            page_id=page_id,
            public=public,
            model=resolved.model,
            content_hash=hashes[index],
            embedding=vectors[position],
        )
    return len(fresh)


async def _fresh_indexes(
    session: AsyncSession,
    table: str,
    id_column: str,
    ids: list[uuid.UUID],
    hashes: list[str],
    model: str,
) -> list[int]:
    """Positions whose (id, hash) is NOT already stored under the active model —
    the hash-skip that makes replays and no-op edits free."""
    result = await session.execute(
        text(
            f"SELECT {id_column}, content_hash FROM {table}"
            f" WHERE {id_column} = ANY(:ids) AND model = :model"
        ),
        {"ids": ids, "model": model},
    )
    stored = {row_id: row_hash for row_id, row_hash in result.all()}
    return [i for i, (row_id, row_hash) in enumerate(zip(ids, hashes)) if stored.get(row_id) != row_hash]
