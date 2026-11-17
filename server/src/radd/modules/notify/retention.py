"""Read notifications do not live forever (RADD-1570).

Nothing removed a notification unless its owner cleared it, so the table only
grew and every inbox carried years of read history. A worker loop deletes inbox
notifications that were READ more than `notify_read_retention_days` ago.

- Measured from `read_at`, not `created_at`: a person who opens a two-month-old
  notification today still has it tomorrow.
- Unread rows are never deleted by age. Nobody has dealt with them, and
  dropping one silently is the tracker losing something it was asked to deliver.
- Email-only rows (`inbox` false) are left alone, as everywhere in the inbox's
  own operations; their cleanup depends on the mailer's delivery states.
- One statement deletes at most `notify_retention_batch` rows and the loop
  drains, so a first run over years of history is many short deletes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.clock import utcnow
from radd.config import settings
from radd.db import SessionLocal

from .models import Notification

logger = logging.getLogger(__name__)


async def sweep(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Delete one batch of expired read notifications; how many went."""
    days = settings.notify_read_retention_days
    if days <= 0:
        return 0
    cutoff = (now or utcnow()) - timedelta(days=days)
    expired = (
        select(Notification.id)
        .where(Notification.inbox.is_(True), Notification.read_at < cutoff)
        .limit(settings.notify_retention_batch)
    )
    result = await session.execute(delete(Notification).where(Notification.id.in_(expired)))
    removed = int(result.rowcount or 0)
    if removed:
        logger.info("notify: deleted %d notification(s) read more than %d days ago", removed, days)
    return removed


async def run_once() -> bool:
    """One loop tick. True while a full batch went, so the loop drains a backlog."""
    async with SessionLocal() as session:
        removed = await sweep(session)
        await session.commit()
    return removed >= settings.notify_retention_batch
