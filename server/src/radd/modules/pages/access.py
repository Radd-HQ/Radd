"""Who may do what in a wiki space (RADD-791).

A space is a SCOPE, the way a project is. Every `page.*` atom used to be checked
globally — which is why per-space access was inexpressible, and why page
commenting was dead for anyone whose grant was scoped: `comments_binding`
resolved `comment.write` with `project=None`, so a project-scoped grant never
reached it.

This module is the pages side of that scope. It does not re-implement
resolution: `authz.effective_permissions(space_id=…)` is the one answer, and
everything here either calls it or batches the same inputs so a list of spaces
costs one query instead of one per row.

Per-PAGE restriction (RADD-792) sits on top and can only ever NARROW what a
space grants — see `page_access.py`.
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
