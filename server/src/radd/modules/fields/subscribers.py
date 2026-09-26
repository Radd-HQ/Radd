"""Project teardown hooks (RADD-1174) — the contract is on `projects.types.ProjectHook`."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.hooks import hooks
from radd.modules.projects.types import ProjectDeleting, ProjectHook, ProjectInspection

from . import service
from .models import FieldProject


def _exclusively_scoped(project_id):
    """Fields whose EVERY scope row names this project — with the rows gone
    (CASCADE) they would have no scope, and "no scope rows" means GLOBAL: the
    deletion would silently promote a project's private field to every
    project on the instance. Deleting the definition is the honest outcome;
    its values live on the items that are going anyway."""
    return (
        select(FieldProject.field_id)
        .group_by(FieldProject.field_id)
        .having(func.bool_and(FieldProject.project_id == project_id))
    )


@hooks.on(ProjectHook.INSPECTING)
async def count_private_fields(session: AsyncSession, inspection: ProjectInspection) -> None:
    ids = list(await session.scalars(_exclusively_scoped(inspection.project.id)))
    inspection.add("fields", len(ids))


@hooks.on(ProjectHook.DELETING)
async def delete_private_fields(session: AsyncSession, deleting: ProjectDeleting) -> None:
    for field_id in list(await session.scalars(_exclusively_scoped(deleting.project.id))):
        await service.delete_field(session, field_id, actor_id=deleting.actor_id)
