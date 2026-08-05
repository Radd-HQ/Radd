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

from radd.modules.auth import authz, grants
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import Role, User
from radd.modules.auth.types import InstanceRole, expand_permissions

from .models import PageSpace


async def space_permissions(
    session: AsyncSession, user: User, space_id: uuid.UUID
) -> frozenset[Permission]:
    """The atoms this actor holds IN one space."""
    return await authz.effective_permissions(session, user, space_id=space_id)


async def permissions_by_space(
    session: AsyncSession, user: User, space_ids: list[uuid.UUID]
) -> dict[uuid.UUID, frozenset[Permission]]:
    """Batched `space_permissions` — the wiki nav resolves every space at once.

    Mirrors `authz.permissions_for_projects`: one instance-role decision, one
    query for the unscoped grants, one for the space-scoped ones, one for the
    role permission sets. Resolving per space would be a query per row.
    """
    if not space_ids:
        return {}
    if not user.active:
        return {space_id: frozenset() for space_id in space_ids}
    if InstanceRole(user.instance_role) is InstanceRole.ADMIN:
        from radd.modules.auth.types import all_permission_keys

        return {space_id: all_permission_keys() for space_id in space_ids}

    unscoped = await grants.unscoped_role_ids(session, user.id)
    per_space = await grants.space_granted_role_ids(session, user.id, space_ids)
    role_ids = set(unscoped) | {r for ids in per_space.values() for r in ids}
    permissions_by_role: dict[uuid.UUID, list[str]] = {}
    if role_ids:
        from sqlalchemy import select

        rows = await session.execute(
            select(Role.id, Role.permissions).where(Role.id.in_(role_ids))
        )
        permissions_by_role = dict(rows.all())

    baseline = await authz.baseline_permissions(session)
    resolved: dict[uuid.UUID, frozenset[Permission]] = {}
    for space_id in space_ids:
        granted: set[str] = {str(p) for p in baseline}
        for role_id in unscoped | per_space.get(space_id, set()):
            granted |= {str(p) for p in permissions_by_role.get(role_id, [])}
        resolved[space_id] = expand_permissions(granted)
    return resolved


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
