"""Bounded subject-grant reads; names never widen the actor's catalog access."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError
from radd.modules.projects.models import Project

from . import authz
from .models import GlobalRoleGrant, Role, User
from .schemas import GrantDirectoryRead
from .types import AuthEntity, GrantScopeKind, Permission


async def grant_window(
    session: AsyncSession, condition, *, limit: int, offset: int
) -> tuple[list[GlobalRoleGrant], int]:
    """One page of matching grants plus the total. Expired rows stay manageable;
    `id` breaks ties, since an import or one request creates many rows at once."""
    total = await session.scalar(select(func.count()).select_from(GlobalRoleGrant).where(condition))
    rows = list(
        (
            await session.scalars(
                select(GlobalRoleGrant)
                .where(condition)
                .order_by(GlobalRoleGrant.created_at, GlobalRoleGrant.id)
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )
    return rows, total or 0


async def role_names(session: AsyncSession, rows: list[GlobalRoleGrant]) -> dict[uuid.UUID, str]:
    return dict(
        (
            await session.execute(
                select(Role.id, Role.name).where(Role.id.in_({row.role_id for row in rows}))
            )
        ).all()
    )


async def subject_page(
    session: AsyncSession,
    actor: User,
    *,
    user_id: uuid.UUID | None = None,
    team_id: uuid.UUID | None = None,
    group_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[GrantDirectoryRead], int]:
    await authz.require_member(session, actor)
    named = [
        (column, value)
        for column, value in (
            (GlobalRoleGrant.user_id, user_id),
            (GlobalRoleGrant.team_id, team_id),
            (GlobalRoleGrant.group_id, group_id),
        )
        if value is not None
    ]
    if len(named) != 1:
        raise ConflictError(AuthEntity.GLOBAL_GRANT, reason="exactly one subject required")
    column, value = named[0]
    rows, total = await grant_window(session, column == value, limit=limit, offset=offset)
    names = {}
    if rows and await authz.holds(session, actor, Permission.ROLE_READ):
        names = await role_names(session, rows)
    visible_projects = await authz.visible_projects(session, actor)
    projects = list(
        (
            await session.scalars(
                select(Project).where(
                    Project.id.in_({row.project_id for row in rows if row.project_id is not None}),
                    Project.id.in_(visible_projects),
                )
            )
        ).all()
    )
    # Use the catalog policy, including qualified own/team/participant access.
    project_names = {project.id: project.key for project in projects}
    space_permissions = await authz.permissions_for_spaces(
        session, actor, list({row.space_id for row in rows if row.space_id is not None})
    )
    visible_spaces = {
        key for key, held in space_permissions.items() if Permission.PAGE_READ in held
    }
    space_names = await authz.scope_labels(session, GrantScopeKind.SPACE, visible_spaces)
    return [
        GrantDirectoryRead(
            **GrantDirectoryRead.model_validate(row).model_dump(
                exclude={"role_name", "scope_label"}
            ),
            role_name=names.get(row.role_id),
            scope_label=project_names.get(row.project_id)
            if row.project_id is not None
            else space_names.get(row.space_id)
            if row.space_id is not None
            else None,
        )
        for row in rows
    ], total
