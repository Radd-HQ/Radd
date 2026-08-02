"""What dies with a comment's parent (RADD-717 / RADD-745).

The polymorphic parent column cannot carry a foreign key, so `ON DELETE CASCADE`
is gone. The delete paths call `service.delete_for_parent` directly, which
handles the common case immediately — but that is a promise every FUTURE delete
path has to remember, and a comment whose parent is gone is invisible in the UI
and unreachable by any API. Nobody would ever notice.

So the guarantee is structural: these cascades are registered on the plugin
manifest and the kernel's single cascade consumer runs them whenever a parent's
`*.deleted` event goes by.

This used to be its own head-seeded consumer with its own poll loop. It is now a
registration, because a `DELETE … WHERE parent = ?` that usually matches nothing
does not deserve a background task of its own (RADD-745).
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from radd.kernel import CascadeSpec

from .models import Comment

logger = logging.getLogger(__name__)


async def _sweep(session: AsyncSession, entity_type: str, parent_id: uuid.UUID) -> None:
    result = await session.execute(
        delete(Comment).where(
            Comment.entity_type == entity_type, Comment.entity_id == parent_id
        )
    )
    # Usually zero: the delete path swept them a moment earlier. A non-zero count
    # means something bypassed that path — which is exactly what this exists to
    # catch, so it is worth a line in the log.
    if result.rowcount:
        logger.info(
            "cascade: %s %s took %d orphaned comment(s)", entity_type, parent_id, result.rowcount
        )


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
