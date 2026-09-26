"""Orphan cleanup (spec 102): a registered kernel CASCADE per parent binding —
the polymorphic parent has no FK, so this is what removes rows, grants and
BYTES. Rows and grants go in the planning transaction, bytes best-effort after
commit."""

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
    """The cleanup that ships with a parent binding (RADD-744/745), so a parent a
    plugin registers is collected too."""
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
) -> list[tuple[uuid.UUID, str]] | None:
    """Delete the parent's rows + grants in the planning transaction (committed
    with the cursor); returns the byte refs for after commit."""
    from .service import purge

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
    doomed = await purge(session, rows)
    logger.info("attachments.gc: parent %s took %d files with it", parent_id, len(doomed))
    return doomed


async def _remove_bytes(doomed: list[tuple[uuid.UUID, str]]) -> None:
    """Post-commit and best-effort: an unreachable host leaves orphans on that
    host, never a stuck consumer."""
    from . import hosts
    from .clients import client_for

    async with SessionLocal() as session:
        for host_id, storage_name in doomed:
            try:
                host = await hosts.get_host(session, host_id)
                await client_for(host).remove(storage_name)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "attachments cascade: could not remove bytes %s", storage_name, exc_info=True
                )
