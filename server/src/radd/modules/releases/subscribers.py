"""Project teardown (RADD-1174): what of ours a project delete counts. The
contract is on `projects.types.ProjectHook`."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.hooks import hooks
from radd.modules.projects.types import ProjectHook, ProjectInspection

from .models import Release


@hooks.on(ProjectHook.INSPECTING)
async def count_releases(session: AsyncSession, inspection: ProjectInspection) -> None:
    inspection.add(
        "releases",
        await session.scalar(
            select(func.count()).select_from(Release).where(Release.project_id == inspection.project.id)
        ),
    )
