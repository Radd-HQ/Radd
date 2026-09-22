"""The far edge of the raw-message retention window (RADD-1048).

RADD-1033 stored the raw inbound bytes and named a window; nothing enforced its
end, so the setting only ever gated whether a NEW message was kept. A window
that only opens is not a window: raw customer mail — the full message, headers
and all — accumulated on a storage host forever while the setting promised it
would not, and a desk that had turned retention down could not make the bytes
it had already collected go away.

**The clock is the trigger, so this is a `PeriodicLoop` and not a consumer.**
The head-seeded `events.runner` idiom the rest of this module uses needs
something to have HAPPENED; nothing emits "this message got old". There is no
cursor to seed and no backlog to replay — just a query that is empty on almost
every tick.

**Bytes first, columns second — the opposite of the attachments orphan-GC, on
purpose.** That collector deletes its rows inside the transaction and removes
bytes afterwards, best-effort, because an unreachable host must leave orphans
rather than a stuck consumer: the pointer is already gone either way. Here the
row is the ONLY pointer to bytes a privacy setting promised to destroy, so a
failed delete leaves the row exactly as it was and the message is swept again
next tick. Nulling the columns first would turn one unreachable host into
customer mail nobody can find and nobody will ever collect — the single outcome
this must not produce.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.clock import utcnow
from radd.db import SessionLocal
from radd.modules.attachments import service as attachments_service
from radd.modules.settings import service as settings_service
from radd.modules.settings.types import SettingKey

from .models import MailMessage
from .types import RAW_SWEEP_BATCH

logger = logging.getLogger(__name__)


async def run_once() -> int:
    """One batch, in its own session. Returns how many messages were stripped —
    the loop drains on a truthy answer, so a backlog built up while retention
    was long is chewed at full speed instead of one batch an hour."""
    async with SessionLocal() as session:
        swept = await sweep(session)
        if swept:
            await session.commit()
        return swept


async def sweep(session: AsyncSession) -> int:
    """Delete the retained blob of every message past the window and null its
    three `raw_*` columns.

    Idempotent by construction: the predicate is the pointer itself, so a
    stripped row can never match again, and a row whose blob has already left
    the host is stripped once (both storage clients treat removing an absent
    object as done). The caller commits.

    Retention of 0 makes the cutoff `now`, which is what lets an admin who
    turns the window off reclaim what is already stored rather than only
    stopping the next message from being kept.
    """
    days = await settings_service.resolve(session, SettingKey.MAIL_RAW_RETENTION_DAYS)
    cutoff = utcnow() - timedelta(days=max(int(days), 0))
    rows = (
        (
            await session.execute(
                select(MailMessage)
                .where(
                    MailMessage.raw_storage_name.is_not(None),
                    MailMessage.created_at < cutoff,
                )
                .order_by(MailMessage.created_at)
                .limit(RAW_SWEEP_BATCH)
            )
        )
        .scalars()
        .all()
    )
    swept = 0
    for row in rows:
        try:
            await attachments_service.remove_blob(
                session, row.raw_storage_name, host_id=row.raw_host_id
            )
        except Exception:  # noqa: BLE001 — `remove_blob` logs; see the module docstring
            continue  # the row keeps its pointer and is swept again next tick
        row.raw_storage_name = None
        row.raw_host_id = None
        row.raw_size_bytes = None
        swept += 1
    if swept:
        # Flush inside the sweep so the UPDATEs are part of the caller's
        # transaction whatever it does next — `run_once` commits, and a caller
        # that reads a row back gets what the sweep decided rather than the
        # pointer the database still holds.
        await session.flush()
        logger.info("mailintake.retention: reclaimed %d raw message(s) past the window", swept)
    return swept
