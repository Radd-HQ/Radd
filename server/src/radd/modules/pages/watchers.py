"""Watching a page (RADD-719).

For a wiki that documents operations, a silently changed runbook is the failure
mode — the only way to know it moved was to reread it.

**Auto-watch on edit**, matching how items behave: touching something is the
strongest available signal that you care what happens to it next, and asking
people to opt in individually is how a watch feature ends up with no watchers.

**Fan-out is NOT here any more** (spec 118). RADD-719 shipped it synchronously,
inside the request that saved the page, on the argument that page edits are rare
and "a consumer would mean a second delivery path to keep correct for a volume
that does not need one". The volume was never the problem: it WAS a second
delivery path, and it drifted exactly where a second path drifts. It knew about
watchers and nothing about the space subscribers spec 118 introduced, and it
wrote notifications without the read gate every item notification passes — so an
edit told whoever had once clicked Watch, whatever the space said about them
since.

What is left is the TABLE and its four accessors. Who hears about an edit is
decided in the one place that decides it for issues, off the `page.updated`
event, by `notify.consumer`.
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
