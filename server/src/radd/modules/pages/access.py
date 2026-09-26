"""Who may do what in a wiki space (RADD-791): a space is a SCOPE, like a project.

Resolution is `authz.effective_permissions(space_id=…)`; this module only calls
or batches it. Per-PAGE restriction narrows on top (`page_access.py`).
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth import authz
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User

from .models import PageSpace


async def space_permissions(
    session: AsyncSession, user: User, space_id: uuid.UUID
) -> frozenset[Permission]:
    """The atoms this actor holds IN one space."""
    return await authz.effective_permissions(session, user, space_id=space_id)


async def permissions_by_space(
    session: AsyncSession, user: User, space_ids: list[uuid.UUID]
) -> dict[uuid.UUID, frozenset[Permission]]:
    """Public pages seam; auth owns the shared direct/batch principal policy."""
    return await authz.permissions_for_spaces(session, user, space_ids)


async def readable_spaces(
    session: AsyncSession, user: User
) -> dict[uuid.UUID, frozenset[Permission]]:
    """Every space this actor may read, with what they hold there.

    The wiki's equivalent of `authz.readable_projects`, and it plays the same
    role: a list surface serves what this returns and answers EMPTY rather than
    refusing when it is empty. Someone entitled to no space is not doing anything
    wrong.
    """
    from sqlalchemy import select

    space_ids = list(
        (await session.execute(select(PageSpace.id).order_by(PageSpace.position))).scalars()
    )
    per_space = await permissions_by_space(session, user, space_ids)
    return {
        space_id: held
        for space_id, held in per_space.items()
        if Permission.PAGE_READ in held
    }


async def all_space_permissions(session, user):
    """Permission catalog for integrations; includes write-only spaces."""
    from sqlalchemy import select
    return await permissions_by_space(session, user, list(await session.scalars(select(PageSpace.id))))
