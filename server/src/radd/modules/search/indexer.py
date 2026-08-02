"""The search outbox consumer: item/comment events → search_index upserts.

First run has no special case: replaying the whole backlog from offset 0 IS the
index build (upserts are idempotent, item.created precedes an item's comments
in the stream).
"""

import logging
import uuid

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import SessionLocal
from radd.modules.comments import service as comments
from radd.modules.comments.types import CommentEvent
from radd.modules.events import service as events
from radd.modules.events.models import Event
from radd.modules.items.enums import ItemEvent

from .models import SearchIndexRow
from .types import CONSUMER_NAME, SEARCH_TS_CONFIG

logger = logging.getLogger(__name__)

_ITEM_EVENTS = {ItemEvent.CREATED.value, ItemEvent.UPDATED.value}
_ITEM_DELETED = ItemEvent.DELETED.value
_COMMENT_EVENTS = {
    CommentEvent.CREATED.value,
    CommentEvent.UPDATED.value,
    CommentEvent.DELETED.value,
}

# The key is indexed in both "TD-123" and "TD 123" token forms so either matches.
_TSV_UPDATE = text(
    f"""
    UPDATE search_index SET tsv =
        setweight(to_tsvector('{SEARCH_TS_CONFIG}',
            key || ' ' || replace(key, '-', ' ') || ' ' || title), 'A') ||
        setweight(to_tsvector('{SEARCH_TS_CONFIG}', description), 'B') ||
        setweight(to_tsvector('{SEARCH_TS_CONFIG}', comments_text), 'C')
    WHERE item_id = :item_id
    """
)


async def run_once() -> int:
    async with SessionLocal() as session:
        offset = await events.get_offset(session, CONSUMER_NAME)
        batch = await events.read_after(session, offset, settings.search_batch)
        if not batch:
            return 0
        for event in batch:
            try:
                async with session.begin_nested():
                    await _handle(session, event)
            except Exception:
                logger.exception("search: failed indexing event %s (%s)", event.id, event.event_type)
        await events.set_offset(session, CONSUMER_NAME, batch[-1].id)
        await session.commit()
        return len(batch)


async def _handle(session: AsyncSession, event: Event) -> None:
    if event.event_type in _ITEM_EVENTS:
        await _index_item(session, event)
    elif event.event_type == _ITEM_DELETED:
        row = await session.get(SearchIndexRow, uuid.UUID(event.entity_id))
        if row is not None:
            await session.delete(row)
    elif event.event_type in _COMMENT_EVENTS:
        await _reindex_comments(session, event)


async def _index_item(session: AsyncSession, event: Event) -> None:
    payload = event.payload or {}
    if "project_id" not in payload:
        return
    row = {
        "item_id": uuid.UUID(event.entity_id),
        "project_id": uuid.UUID(payload["project_id"]),
        "key": payload.get("key", ""),
        "title": payload.get("title", ""),
        "description": payload.get("description", ""),
    }
    await session.execute(
        pg_insert(SearchIndexRow)
        .values(**row)
        .on_conflict_do_update(
            index_elements=[SearchIndexRow.item_id],
            set_={k: v for k, v in row.items() if k != "item_id"},
        )
    )
    await session.execute(_TSV_UPDATE, {"item_id": row["item_id"]})


async def _reindex_comments(session: AsyncSession, event: Event) -> None:
    payload = event.payload or {}
    item_id = uuid.UUID(payload["item_id"])
    row = await session.get(SearchIndexRow, item_id)
    if row is None:
        return  # item never indexed (shouldn't happen — created precedes comments)
    # Public bodies only: internal-comment text must not be findable via plain item.read.
    bodies = await comments.public_bodies_for_item(session, item_id)
    row.comments_text = "\n".join(bodies)
    await session.flush()
    await session.execute(_TSV_UPDATE, {"item_id": item_id})
