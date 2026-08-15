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
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import SessionLocal

from .models import Attachment

if TYPE_CHECKING:  # deferred at runtime: the kernel loads after this module
    from radd.kernel import CascadeSpec

logger = logging.getLogger(__name__)


def cascades() -> tuple["CascadeSpec", ...]:
    """One per registered parent — derived, so a plugin gets byte-collection
    with no edit to this module."""
    from .parents import bindings

    return tuple(_cascade_for(binding) for binding in bindings())


def _cascade_for(binding) -> "CascadeSpec":
    """The cleanup that ships with a parent binding (RADD-744/745).

    This was a hardcoded map inside this module, which meant a parent registered
    by a PLUGIN — the seam the binding registry exists for — got no cleanup, and
    its bytes stayed on a storage host forever with nothing pointing at them.
    """
    from radd.kernel import CascadeSpec

    entity_type = binding.entity_type

    async def sweep(session: AsyncSession, parent_id: uuid.UUID):
        return await _sweep(session, entity_type, parent_id)

    return CascadeSpec(
        parent_event=binding.deleted_event,
        name=f"attachments:{entity_type}",
        sweep=sweep,
        after_commit=_remove_bytes,
    )


async def _sweep(
    session: AsyncSession, entity_type: str, parent_id: uuid.UUID
) -> list[tuple[uuid.UUID, uuid.UUID, str]] | None:
    """Collect (attachment_id, host_id, storage_name), delete rows + grants in
    the planning transaction (committed with the cursor); bytes go post-commit."""
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


async def _remove_bytes(doomed: list[tuple[uuid.UUID, uuid.UUID, str]]) -> None:
    """Byte removal, post-commit and best-effort — an unreachable host leaves
    orphans on that host, never a stuck consumer."""
    from . import hosts
    from .clients import client_for

    async with SessionLocal() as session:
        for _attachment_id, host_id, storage_name in doomed:
            try:
                host = await hosts.get_host(session, host_id)
                await client_for(host).remove(storage_name)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "attachments cascade: could not remove bytes %s", storage_name, exc_info=True
                )
