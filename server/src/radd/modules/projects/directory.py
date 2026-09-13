"""Project directory reads page after the shared authorization decision.

Legacy callers may omit a limit. Interactive readers use bounded pages and the
separate summary, so neither their permissions nor direct links depend on which
page happens to be loaded. Authority resolution loads project IDs, not content.
"""
import uuid
from typing import TYPE_CHECKING
from collections.abc import Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import ilike_term
from radd.exceptions import NotFoundError
from radd.modules.auth import authz
from radd.modules.auth.types import Permission
from radd.modules.auth.models import User

if TYPE_CHECKING:
    from radd.modules.auth.public_access import PublicAccess

from .models import Project
from .schemas import ProjectRead, ProjectSummaryRead
from .types import ProjectEntity


def project_read(
    project: Project, permissions: Iterable[str], via: str | None = None,
    access: "PublicAccess | None" = None,
) -> ProjectRead:
    return ProjectRead.model_validate(project).model_copy(update={
        "permissions": sorted(permissions), "via": via,
        "public": access.public if access else False,
        "contributions": access.contributions if access else False,
    })


async def project_read_with_access(
    session: AsyncSession, project: Project, permissions: Iterable[str], via: str | None = None,
) -> ProjectRead:
    """One project + its spec-121 public-access switches (one grants query)."""
    from radd.modules.auth import public_access  # deferred: auth loads after projects

    return project_read(
        project, permissions, via, access=await public_access.public_access(session, project.id)
    )


async def summary(session: AsyncSession, actor: User) -> ProjectSummaryRead:
    visible = await authz.visible_projects(session, actor)
    return ProjectSummaryRead(
        total=len(visible),
        related_count=sum(row.via.value == "related" for row in visible.values()),
        permissions=sorted({permission for row in visible.values() for permission in row.permissions}),
    )


async def page(
    session: AsyncSession, actor: User, *, q: str = "", limit: int | None = None,
    offset: int = 0, hide_related: bool = False, ids: list[uuid.UUID] | None = None,
    permission: Permission | None = None,
) -> tuple[list[ProjectRead], int]:
    visible = await authz.visible_projects(session, actor)
    allowed = [
        identifier for identifier, row in visible.items()
        if (not hide_related or row.via.value != "related")
        and (permission is None or permission in row.permissions)
    ]
    query = select(Project).where(Project.id.in_(allowed))
    if ids is not None:
        query = query.where(Project.id.in_(ids))
    if q.strip():
        term = ilike_term(q.strip())
        query = query.where(or_(Project.key.ilike(term), Project.name.ilike(term)))
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    query = query.order_by(Project.created_at, Project.id).offset(offset)
    if limit is not None:
        query = query.limit(limit)
    rows = (await session.scalars(query)).all()
    from radd.modules.auth import public_access  # deferred: auth loads after projects

    access = await public_access.public_access_for_projects(session, [row.id for row in rows])
    return [
        project_read(row, visible[row.id].permissions, visible[row.id].via.value, access.get(row.id))
        for row in rows
    ], total or 0


async def by_identity(
    session: AsyncSession, actor: User, *, identifier: uuid.UUID | None = None, key: str | None = None,
) -> ProjectRead:
    if identifier is not None:
        query = select(Project).where(Project.id == identifier)
    else:
        query = select(Project).where(Project.key == (key or "").upper())
    project = await session.scalar(query)
    visible = await authz.visible_projects(session, actor)
    if project is None or project.id not in visible:
        raise NotFoundError(ProjectEntity.PROJECT, identifier or key)
    row = visible[project.id]
    return await project_read_with_access(session, project, row.permissions, row.via.value)
