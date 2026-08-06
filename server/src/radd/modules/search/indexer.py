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
from radd.modules.access import service as access_service
from radd.modules.access.types import Access, AccessEvent
from radd.modules.auth.types import AuthEvent
from radd.modules.comments import service as comments
from radd.modules.comments.types import CommentEvent
from radd.modules.events import service as events
from radd.modules.events.service import Event
from radd.modules.fields.service import BUILTIN_RESOURCE
from radd.modules.fields.types import BuiltinItemField
from radd.modules.items.enums import ItemEvent
from radd.modules.teams.types import TeamEvent

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
_ACCESS_EVENTS = {AccessEvent.GRANTED.value, AccessEvent.REVOKED.value}
# RADD-841: bulk repoints that never emit item events — user merge/delete
# rewrites work_items.assignee_id/reporter_id in SQL, a team delete nulls
# team_id via FK — so the relation mirror re-syncs when one of these lands.
_SUBJECT_EVENTS = {AuthEvent.USER_DELETED.value, TeamEvent.DELETED.value}
_DESCRIPTION = BuiltinItemField.DESCRIPTION.value

# RADD-840: `description` is read-restrictable AND searchable. Conservative
# indexing — the internal-comments precedent ("public text only by
# construction"): where a read-restricting grant covers a project, its items'
# descriptions index for NOBODY, so snippets, similar-issues and the embedding
# provider can never carry text some readers may not see. Synced once at
# consumer start and again on every description read-grant change.
_restriction_synced = False

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
    global _restriction_synced
    async with SessionLocal() as session:
        if not _restriction_synced:
            # A restriction written while the consumer was down (or before this
            # release) is honored on start, not on the next grant change.
            await sync_description_restriction(session)
            await sync_relation_columns(session)
            _restriction_synced = True
        offset = await events.get_offset(session, CONSUMER_NAME)
        batch = await events.read_after(session, offset, settings.search_batch)
        if not batch:
            await session.commit()
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
    elif event.event_type in _ACCESS_EVENTS and _touches_description_read(event):
        await sync_description_restriction(session)
    elif event.event_type in _SUBJECT_EVENTS:
        await sync_relation_columns(session)


def _touches_description_read(event: Event) -> bool:
    payload = event.payload or {}
    return (
        payload.get("resource_type") == BUILTIN_RESOURCE
        and payload.get("resource_id") == _DESCRIPTION
        and payload.get("access") == Access.READ.value
    )


async def _restricted_scope(session: AsyncSession) -> tuple[bool, set[uuid.UUID]]:
    """(restricted everywhere, project ids restricted) from the read grants on
    the `description` builtin. Any read grant restricts — for everybody, holders
    included: index text must be one-per-row, and a per-reader index is not."""
    grants = await access_service.grants_for_resources(session, BUILTIN_RESOURCE, [_DESCRIPTION])
    read_rows = [g for g in grants.get(_DESCRIPTION, ()) if g.access == Access.READ.value]
    return (
        any(g.project_id is None for g in read_rows),
        {g.project_id for g in read_rows if g.project_id is not None},
    )


async def _index_item(session: AsyncSession, event: Event) -> None:
    # RADD-922: one nested `item`, so the guard is "is this an item event at
    # all" rather than the old `if "project_id" not in payload: return` — which
    # made a payload missing a field indistinguishable from an item that should
    # not be indexed.
    item = (event.payload or {}).get("item") or {}
    if not item:
        return
    project_id = uuid.UUID((item.get("project") or {})["id"])
    everywhere, scoped = await _restricted_scope(session)
    restricted = everywhere or project_id in scoped
    row = {
        "item_id": uuid.UUID(event.entity_id),
        "project_id": project_id,
        "key": item.get("key", ""),
        "title": item.get("title", ""),
        "description": "" if restricted else item.get("description", ""),
    }
    # RADD-841: relation anchors, only when the payload SPEAKS about them — a
    # partial payload must not null a good mirror (the startup sweep repairs
    # real drift from work_items itself).
    for column, ref_key in (
        ("reporter_id", "reporter"),
        ("assignee_id", "assignee"),
        ("team_id", "team"),
    ):
        if ref_key in item:
            ref = item.get(ref_key) or {}
            row[column] = uuid.UUID(ref["id"]) if ref.get("id") else None
    await session.execute(
        pg_insert(SearchIndexRow)
        .values(**row)
        .on_conflict_do_update(
            index_elements=[SearchIndexRow.item_id],
            set_={k: v for k, v in row.items() if k != "item_id"},
        )
    )
    await session.execute(_TSV_UPDATE, {"item_id": row["item_id"]})


# Bulk forms of _TSV_UPDATE for the restriction sweep: recompute tsv inline
# with the row's NEW description in the same statement, bounded to rows whose
# text actually changes.
_BLANK_RESTRICTED = text(
    f"""
    UPDATE search_index SET description = '', tsv =
        setweight(to_tsvector('{SEARCH_TS_CONFIG}',
            key || ' ' || replace(key, '-', ' ') || ' ' || title), 'A') ||
        setweight(to_tsvector('{SEARCH_TS_CONFIG}', comments_text), 'C')
    WHERE description <> ''
      AND (:everywhere OR project_id = ANY(:project_ids))
    """
)
# Restore reads work_items directly — the timesheet's "tolerated inward read of
# dependency tables" precedent: the description came FROM that table via event
# payloads, and only the owning row can put it back.
_RESTORE_OPEN = text(
    f"""
    UPDATE search_index si SET description = COALESCE(wi.description, ''), tsv =
        setweight(to_tsvector('{SEARCH_TS_CONFIG}',
            si.key || ' ' || replace(si.key, '-', ' ') || ' ' || si.title), 'A') ||
        setweight(to_tsvector('{SEARCH_TS_CONFIG}', COALESCE(wi.description, '')), 'B') ||
        setweight(to_tsvector('{SEARCH_TS_CONFIG}', si.comments_text), 'C')
    FROM work_items wi
    WHERE wi.id = si.item_id
      AND NOT (:everywhere OR si.project_id = ANY(:project_ids))
      AND si.description IS DISTINCT FROM COALESCE(wi.description, '')
    """
)


# RADD-841: repair the relation mirror from the owning table, bounded to rows
# that actually drifted (the sync_description_restriction idiom).
_RELATION_SYNC = text(
    """
    UPDATE search_index si SET
        reporter_id = wi.reporter_id,
        assignee_id = wi.assignee_id,
        team_id = wi.team_id
    FROM work_items wi
    WHERE wi.id = si.item_id
      AND (si.reporter_id IS DISTINCT FROM wi.reporter_id
        OR si.assignee_id IS DISTINCT FROM wi.assignee_id
        OR si.team_id IS DISTINCT FROM wi.team_id)
    """
)


async def sync_relation_columns(session: AsyncSession) -> None:
    """Re-mirror reporter/assignee/team from `work_items` wherever they drifted
    (RADD-841). Item events keep the mirror current row by row; this covers the
    writes that never emit them — a user merge/delete repoints assignee_id and
    reporter_id in bulk SQL, deleting a team nulls team_id through the FK — and
    anything missed while the consumer was down. Idempotent, bounded."""
    await session.execute(_RELATION_SYNC)


async def sync_description_restriction(session: AsyncSession) -> None:
    """Blank indexed descriptions where a read-restriction covers the project;
    restore them where none does. Idempotent, bounded to rows whose text
    changes; run at consumer start and on description read-grant changes."""
    everywhere, scoped = await _restricted_scope(session)
    params = {"everywhere": everywhere, "project_ids": list(scoped)}
    await session.execute(_BLANK_RESTRICTED, params)
    await session.execute(_RESTORE_OPEN, params)


async def _reindex_comments(session: AsyncSession, event: Event) -> None:
    payload = event.payload or {}
    item_id = uuid.UUID((payload.get("item") or {})["id"])
    row = await session.get(SearchIndexRow, item_id)
    if row is None:
        return  # item never indexed (shouldn't happen — created precedes comments)
    # Public bodies only: internal-comment text must not be findable via plain item.read.
    bodies = await comments.public_bodies_for_item(session, item_id)
    row.comments_text = "\n".join(bodies)
    await session.flush()
    await session.execute(_TSV_UPDATE, {"item_id": item_id})
