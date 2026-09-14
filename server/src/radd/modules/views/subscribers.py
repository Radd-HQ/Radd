from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.hooks import hooks
from radd.modules.projects.models import Project
from radd.modules.access import service as access_service
from radd.modules.projects.types import (
    ProjectDeleting,
    ProjectEvent,
    ProjectHook,
    ProjectInspection,
)

from . import defaults
from .models import View
from .service import VIEW_RESOURCE


@hooks.on(ProjectEvent.PROJECT_CREATED)
async def seed_builtin_views(session: AsyncSession, project: Project) -> None:
    """Every project ships with its Board/List/Planning/Roadmap as real,
    editable views (same in-txn idiom as workflow's default states)."""
    await defaults.seed_project_views(session, project)


# --- teardown (RADD-1174): the mirror image of the seeding above ---------------


@hooks.on(ProjectHook.INSPECTING)
async def count_views(session: AsyncSession, inspection: ProjectInspection) -> None:
    inspection.add(
        "views",
        await session.scalar(
            select(func.count()).select_from(View).where(View.project_id == inspection.project.id)
        ),
    )


@hooks.on(ProjectHook.DELETING)
async def clear_view_grants(session: AsyncSession, deleting: ProjectDeleting) -> None:
    """The rows themselves go with the `ProjectPurgeSpec`; their share grants
    (spec 92) key to the view by bare id and would dangle."""
    for view_id in await session.scalars(select(View.id).where(View.project_id == deleting.project.id)):
        await access_service.clear_resource(session, VIEW_RESOURCE, str(view_id))
