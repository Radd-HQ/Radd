"""Page watchers (RADD-719): the table and its accessors. Editing auto-watches
(`service.update_page`); who hears about an edit is decided by `notify` off the
`page.updated` event, through this plugin's NOTIFICATION_SUBJECT provider.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import PageWatcher


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
