"""Management windows; permission-safe names never widen catalog access."""

import uuid

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.clock import utcnow
from radd.db import ilike_term
from radd.modules.auth import authz
from radd.modules.auth.models import Role, User
from radd.modules.auth.types import Permission, UserSource
from radd.modules.groups.service import Group
from radd.modules.projects.models import Project
from radd.modules.teams.models import Team

from .models import AccessGrant
from .schemas import AccessGrantDirectoryRead
from .types import GrantSubject


async def page(
    session: AsyncSession,
    actor: User,
    resource_type: str,
    resource_id: str,
    *,
    project_id: uuid.UUID | None = None,
    global_only: bool = False,
    q: str = "",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AccessGrantDirectoryRead], int]:
    # The router checks the resource registry's can_manage before calling us.
    role_read = await authz.holds(session, actor, Permission.ROLE_READ)
    team_read = await authz.holds(session, actor, Permission.TEAM_READ)
    group_read = bool(await authz.readable_projects(session, actor))
    visible_projects = await authz.visible_projects(session, actor)
    projections = {
        # Names EXISTING grant subjects, so the principals (spec 121: "Anyone",
        # "Signed-in users") must resolve here — only mail-provisioned
        # requesters stay unnamed. Pickers exclude principals separately.
        GrantSubject.USER: select(User.id, User.name).where(User.source != UserSource.EMAIL),
        GrantSubject.ROLE: select(Role.id, Role.name).where(role_read),
        GrantSubject.TEAM: select(Team.id, Team.name).where(team_read),
        GrantSubject.GROUP: select(Group.id, Group.name).where(group_read),
    }
    project_projection = select(Project.id, Project.key).where(Project.id.in_(visible_projects))
    condition = and_(
        AccessGrant.resource_type == resource_type, AccessGrant.resource_id == resource_id
    )
    if project_id is not None:
        condition &= AccessGrant.project_id == project_id
    elif global_only:
        condition &= AccessGrant.project_id.is_(None)
    if q.strip():
        term = ilike_term(q.strip())
        terms = [AccessGrant.access.ilike(term), AccessGrant.effect.ilike(term)]
        for kind, projection in projections.items():
            named = projection.subquery()
            terms.append(
                and_(
                    AccessGrant.subject_type == kind,
                    AccessGrant.subject_id.in_(select(named.c.id).where(named.c.name.ilike(term))),
                )
            )
        projects = project_projection.subquery()
        terms.append(
            AccessGrant.project_id.in_(select(projects.c.id).where(projects.c.key.ilike(term)))
        )
        condition &= or_(*terms)
    total = await session.scalar(select(func.count()).select_from(AccessGrant).where(condition))
    rows = list(
        (
            await session.scalars(
                select(AccessGrant)
                .where(condition)
                .order_by(AccessGrant.created_at, AccessGrant.id)
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )
    names: dict[tuple[str, uuid.UUID], str] = {}
    for kind, projection in projections.items():
        ids = {row.subject_id for row in rows if row.subject_type == kind}
        if ids:
            named = projection.subquery()
            for identifier, name in await session.execute(
                select(named.c.id, named.c.name).where(named.c.id.in_(ids))
            ):
                names[kind, identifier] = name
    project_ids = {row.project_id for row in rows if row.project_id is not None}
    project_names = (
        dict((await session.execute(project_projection.where(Project.id.in_(project_ids)))).all())
        if project_ids
        else {}
    )
    now = utcnow()
    return [
        AccessGrantDirectoryRead(
            **AccessGrantDirectoryRead.model_validate(row).model_dump(
                exclude={"subject_name", "project_key", "expired"}
            ),
            subject_name=names.get((row.subject_type, row.subject_id)),
            project_key=project_names.get(row.project_id),
            expired=row.expires_at is not None and row.expires_at <= now,
        )
        for row in rows
    ], total or 0
