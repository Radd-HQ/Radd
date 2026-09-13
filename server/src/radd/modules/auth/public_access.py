"""A project's PUBLIC ACCESS, read and written as the two grants it is (spec 121 §1).

"Public project" = the seeded Public role granted to the Anyone principal on
the project. "Anyone signed in may contribute" = the seeded Contributor role
granted to the Signed-in users principal. This module is a PRESENTATION of
those two rows for the project's Access screen and the project payload —
never a second mechanism: `GET /role-grants?project_id=` lists the same rows,
the inspector explains them, and deleting either row there is the same act as
flipping the switch here.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError
from radd.modules.projects.models import Project

from . import grants
from .models import GlobalRoleGrant, Role
from .principals import ANYONE_ID, SIGNED_IN_ID
from .types import AuthEntity, BuiltinRoleKey


@dataclass(frozen=True)
class PublicAccess:
    #: The Public role is granted to Anyone here.
    public: bool = False
    #: The Contributor role is granted to Signed-in users here.
    contributions: bool = False


#: (principal, builtin role) per switch — the whole vocabulary of this module.
_SWITCHES: tuple[tuple[str, uuid.UUID, BuiltinRoleKey], ...] = (
    ("public", ANYONE_ID, BuiltinRoleKey.PUBLIC),
    ("contributions", SIGNED_IN_ID, BuiltinRoleKey.CONTRIBUTOR),
)


async def _switch_roles(session: AsyncSession) -> dict[BuiltinRoleKey, uuid.UUID]:
    rows = await session.execute(
        select(Role.key, Role.id).where(Role.key.in_([key.value for _, _, key in _SWITCHES]))
    )
    return {BuiltinRoleKey(key): role_id for key, role_id in rows.all()}


async def public_access_for_projects(
    session: AsyncSession, project_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, PublicAccess]:
    """Batch: {project_id: PublicAccess} — one query for a page of projects."""
    ids = list(project_ids)
    if not ids:
        return {}
    roles = await _switch_roles(session)
    wanted = {(principal, roles[key]): name for name, principal, key in _SWITCHES if key in roles}
    if not wanted:
        return {pid: PublicAccess() for pid in ids}
    rows = await session.execute(
        select(GlobalRoleGrant.project_id, GlobalRoleGrant.user_id, GlobalRoleGrant.role_id).where(
            GlobalRoleGrant.project_id.in_(ids),
            GlobalRoleGrant.user_id.in_([ANYONE_ID, SIGNED_IN_ID]),
            GlobalRoleGrant.role_id.in_(list(roles.values())),
        )
    )
    flags: dict[uuid.UUID, dict[str, bool]] = {pid: {} for pid in ids}
    for project_id, user_id, role_id in rows.all():
        name = wanted.get((user_id, role_id))
        if name is not None:
            flags[project_id][name] = True
    return {pid: PublicAccess(**values) for pid, values in flags.items()}


async def public_access(session: AsyncSession, project_id: uuid.UUID) -> PublicAccess:
    return (await public_access_for_projects(session, [project_id])).get(project_id, PublicAccess())


async def set_public_access(
    session: AsyncSession,
    project: Project,
    *,
    public: bool,
    contributions: bool,
    actor_id: uuid.UUID | None,
) -> PublicAccess:
    """Write the switches as grants. Contributions need the project public —
    a Contributor grant on a private project is unreachable by construction
    (nobody outside can see the project to file into it), so it is refused
    rather than left as a row that grants nothing."""
    if contributions and not public:
        raise ConflictError(
            AuthEntity.GLOBAL_GRANT,
            reason="contributions from signed-in users need the project to be public",
        )
    roles = await _switch_roles(session)
    current = await public_access(session, project.id)
    wanted = {"public": public, "contributions": contributions}
    for name, principal, key in _SWITCHES:
        if key not in roles:
            raise ConflictError(AuthEntity.ROLE, reason=f"builtin role '{key}' is not seeded")
        have, want = getattr(current, name), wanted[name]
        if have == want:
            continue
        if want:
            await grants.create_grant(
                session, roles[key], user_id=principal, project_id=project.id, actor_id=actor_id
            )
        else:
            row = await session.scalar(
                select(GlobalRoleGrant).where(
                    GlobalRoleGrant.project_id == project.id,
                    GlobalRoleGrant.user_id == principal,
                    GlobalRoleGrant.role_id == roles[key],
                )
            )
            if row is not None:
                await grants.delete_grant(session, row.id, actor_id=actor_id)
    return PublicAccess(public=public, contributions=contributions)
