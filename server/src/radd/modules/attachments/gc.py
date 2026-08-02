"""Orphan GC (spec 102): when a parent dies, its attachments' rows, BYTES, and
grants go too.

With the polymorphic parent there is no FK cascade — and the old cascade only
ever deleted rows, orphaning bytes forever (the spec-29 known gap). This
consumer is therefore the correctness mechanism, not an optimization. It is
head-seeded (the historical backlog must not replay as deletes) and processes
`item.deleted` / `page.deleted` events.
"""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import SessionLocal
from radd.modules.events import runner
from radd.modules.events.models import Event
from radd.worker import PeriodicLoop

from .models import Attachment
from .types import AttachmentParentType

logger = logging.getLogger(__name__)

CONSUMER_NAME = "attachments.gc"

_PARENT_DELETES = {
    "item.deleted": AttachmentParentType.ITEM.value,
    "page.deleted": AttachmentParentType.PAGE.value,
}


async def run_once() -> int:
    return await runner.run_head_seeded(
        CONSUMER_NAME, batch_size=50, plan=_plan, deliver=_deliver
    )


async def _plan(
    session: AsyncSession, event: Event
) -> list[tuple[uuid.UUID, uuid.UUID, str]] | None:
    """Collect (attachment_id, host_id, storage_name), delete rows + grants in
    the planning transaction (committed with the cursor); bytes go post-commit."""
    entity_type = _PARENT_DELETES.get(event.event_type)
    if entity_type is None:
        return None
    try:
        parent_id = uuid.UUID(str(event.entity_id))
    except ValueError:
        return None
    rows = list(
        (
            await session.execute(
                select(Attachment).where(
                    Attachment.entity_type == entity_type, Attachment.entity_id == parent_id
                )
            )
        ).scalars()
    )
    if not rows:
        return None
    from radd.modules.access import service as access_service

    from .acl import ATTACHMENT_RESOURCE

    doomed: list[tuple[uuid.UUID, uuid.UUID, str]] = []
    for attachment in rows:
        doomed.append((attachment.id, attachment.storage_host_id, attachment.storage_name))
        await access_service.clear_resource(session, ATTACHMENT_RESOURCE, str(attachment.id))
        await session.delete(attachment)
    logger.info("attachments.gc: parent %s took %d files with it", parent_id, len(doomed))
    return doomed


async def _deliver(plans: list[list[tuple[uuid.UUID, uuid.UUID, str]]]) -> None:
    """Byte removal, post-commit and best-effort — an unreachable host leaves
    orphans on that host, never a stuck consumer."""
    from . import hosts
    from .clients import client_for

    async with SessionLocal() as session:
        for doomed in plans:
            for _attachment_id, host_id, storage_name in doomed:
                try:
                    host = await hosts.get_host(session, host_id)
                    await client_for(host).remove(storage_name)
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "attachments.gc: could not remove bytes %s", storage_name, exc_info=True
                    )


_loop = PeriodicLoop(
    run_once,
    interval=lambda: settings.search_poll_interval,  # the indexers' cadence fits
    name="attachments-gc",
    enabled=lambda: settings.run_workers,
)

start = _loop.start
stop = _loop.stop
