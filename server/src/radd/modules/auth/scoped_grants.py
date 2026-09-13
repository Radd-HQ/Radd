"""Project/wiki grant windows with scope gates and permission-safe name hydration."""

import uuid
from typing import Literal
from radd.exceptions import NotFoundError
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from radd.clock import utcnow
from radd.db import ilike_term
from . import authz
from .models import GlobalRoleGrant, Role, User
from .schemas import SpaceGrantDirectoryRead
from .types import NON_PERSON_SOURCES, Permission, GrantScopeKind


async def page(
    session: AsyncSession,
    actor: User,
    scope_id: uuid.UUID,
    scope_kind: Literal[GrantScopeKind.SPACE, GrantScopeKind.PROJECT],
    *,
    q: str = "",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[SpaceGrantDirectoryRead], int]:
    from radd.modules.teams.models import Team  # read-only spine projection
    from radd.modules.groups.service import Group  # public group type

    if scope_kind == GrantScopeKind.SPACE:
        await authz.require(session, actor, Permission.PAGE_READ, space_id=scope_id)
    else:
        await require_project_scope(session, actor, scope_id)
    role_read = await authz.holds(session, actor, Permission.ROLE_READ)
    team_read = await authz.holds(session, actor, Permission.TEAM_READ)
    group_read = bool(await authz.readable_projects(session, actor))
    condition = (GlobalRoleGrant.space_id if scope_kind == GrantScopeKind.SPACE else GlobalRoleGrant.project_id) == scope_id
    if q.strip():
        term = ilike_term(q.strip())
        terms = [
            GlobalRoleGrant.user_id.in_(
                select(User.id).where(User.name.ilike(term), User.source.notin_(NON_PERSON_SOURCES))
            )
        ]
        if role_read:
            terms.append(
                GlobalRoleGrant.role_id.in_(
                    select(Role.id).where(or_(Role.name.ilike(term), Role.key.ilike(term)))
                )
            )
        if team_read:
            terms.append(GlobalRoleGrant.team_id.in_(select(Team.id).where(Team.name.ilike(term))))
        if group_read:
            terms.append(
                GlobalRoleGrant.group_id.in_(select(Group.id).where(Group.name.ilike(term)))
            )
        condition &= or_(*terms)
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
    role_names = (
        dict(
            (
                await session.execute(
                    select(Role.id, Role.name).where(Role.id.in_({row.role_id for row in rows}))
                )
            ).all()
        )
        if role_read and rows
        else {}
    )
    people = {
        row.id: row
        for row in (
            await session.execute(
                select(User.id, User.name, User.active).where(
                    User.id.in_({row.user_id for row in rows if row.user_id}),
                    User.source.notin_(NON_PERSON_SOURCES),
                )
            )
        ).all()
    }
    team_names = (
        dict(
            (
                await session.execute(
                    select(Team.id, Team.name).where(
                        Team.id.in_({row.team_id for row in rows if row.team_id})
                    )
                )
            ).all()
        )
        if team_read and rows
        else {}
    )
    group_names = (
        dict(
            (
                await session.execute(
                    select(Group.id, Group.name).where(
                        Group.id.in_({row.group_id for row in rows if row.group_id})
                    )
                )
            ).all()
        )
        if group_read and rows
        else {}
    )
    now = utcnow()
    return [
        SpaceGrantDirectoryRead(
            **SpaceGrantDirectoryRead.model_validate(row).model_dump(
                exclude={"role_name", "subject_name", "subject_active", "expired"}
            ),
            role_name=role_names.get(row.role_id),
            subject_name=people[row.user_id].name
            if row.user_id in people
            else team_names.get(row.team_id)
            if row.team_id
            else group_names.get(row.group_id),
            subject_active=people[row.user_id].active if row.user_id in people else None,
            expired=row.expires_at is not None and row.expires_at <= now,
        )
        for row in rows
    ], total or 0


async def require_project_scope(session: AsyncSession, actor: User, project_id: uuid.UUID) -> None:
    """Match the public project directory, including real qualified relationships."""
    if project_id not in await authz.visible_projects(session, actor):
        raise NotFoundError("project", project_id)
