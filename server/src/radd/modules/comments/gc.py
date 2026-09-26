"""What dies with a comment's parent (RADD-717).

The polymorphic parent column has no foreign key, so no ON DELETE CASCADE.
Delete paths call `service.delete_for_parent`, but a future path that forgets
would leave comments no UI or API can reach. These cascades, derived from the
parent bindings and run by the kernel's cascade consumer on each parent's
`*.deleted` event, make the cleanup structural.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from radd.kernel import CascadeSpec

from .service import delete_for_parent

logger = logging.getLogger(__name__)


async def _sweep(session: AsyncSession, entity_type: str, parent_id: uuid.UUID) -> None:
    swept = await delete_for_parent(session, entity_type, parent_id)
    # Usually zero: the delete path swept them a moment earlier. A non-zero count
    # means something bypassed that path — exactly what this exists to catch.
    if swept:
        logger.info("cascade: %s %s took %d orphaned comment(s)", entity_type, parent_id, swept)


def cascades() -> tuple[CascadeSpec, ...]:
    """One per registered parent — derived, so a plugin that registers a
    `CommentParent` gets cleanup with no edit to this module."""
    from .parents import bindings

    return tuple(_cascade_for(binding) for binding in bindings())


def _cascade_for(binding) -> CascadeSpec:
    entity_type = binding.entity_type

    async def sweep(session: AsyncSession, parent_id: uuid.UUID) -> None:
        await _sweep(session, entity_type, parent_id)

    return CascadeSpec(
        parent_event=binding.deleted_event,
        name=f"comments:{entity_type}",
        sweep=sweep,
    )
