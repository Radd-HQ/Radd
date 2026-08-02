"""Watching a page (RADD-719).

For a wiki that documents operations, a silently changed runbook is the failure
mode — the only way to know it moved was to reread it.

**Auto-watch on edit**, matching how items behave: touching something is the
strongest available signal that you care what happens to it next, and asking
people to opt in individually is how a watch feature ends up with no watchers.

**Fan-out is synchronous**, unlike the item path which goes through an outbox
consumer. Page edits are orders of magnitude rarer than item events, the
recipient list is a handful of people, and a consumer would mean a second
delivery path to keep correct for a volume that does not need one. If page edits
ever look like item events, this moves behind the consumer — the notification
call is already the shared one.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.notify import service as notify
from radd.modules.notify.types import NotificationType

from .models import Page, PageWatcher


async def watch(session: AsyncSession, page_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Idempotent: watching twice is not an error, it is a double click."""
    if await is_watching(session, page_id, user_id):
        return
    session.add(PageWatcher(page_id=page_id, user_id=user_id))
    await session.flush()


async def unwatch(session: AsyncSession, page_id: uuid.UUID, user_id: uuid.UUID) -> None:
    await session.execute(
        delete(PageWatcher).where(
            PageWatcher.page_id == page_id, PageWatcher.user_id == user_id
        )
    )
    await session.flush()


async def is_watching(session: AsyncSession, page_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    row = await session.execute(
        select(PageWatcher.user_id).where(
            PageWatcher.page_id == page_id, PageWatcher.user_id == user_id
        )
    )
    return row.scalar_one_or_none() is not None


async def watcher_ids(session: AsyncSession, page_id: uuid.UUID) -> list[uuid.UUID]:
    rows = await session.execute(
        select(PageWatcher.user_id).where(PageWatcher.page_id == page_id)
    )
    return list(rows.scalars())


async def notify_watchers(
    session: AsyncSession, page: Page, actor_id: uuid.UUID, space_slug: str, version: int
) -> int:
    """Tell everyone watching, except whoever made the change.

    The payload carries what the inbox row needs to render and to link — title,
    slugs, the version — resolved now rather than joined later, the same way item
    notifications do it, so the entry stays accurate after a rename.
    """
    recipients = [uid for uid in await watcher_ids(session, page.id) if uid != actor_id]
    for user_id in recipients:
        await notify.create_notification(
            session,
            user_id=user_id,
            type_=NotificationType.PAGE_UPDATED,
            event_id=None,
            item_id=None,
            actor_id=actor_id,
            payload={
                "page_id": str(page.id),
                "page_slug": page.slug,
                "space_slug": space_slug,
                "title": page.title,
                "version": version,
            },
        )
    return len(recipients)
