"""Project teardown (RADD-1174): what of ours a project delete counts. The
contract is on `projects.types.ProjectHook`."""

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.hooks import hooks
from radd.modules.items.models import WorkItem
from radd.modules.projects.types import ProjectHook, ProjectInspection

from .models import Worklog


@hooks.on(ProjectHook.INSPECTING)
async def count_worklogs(session: AsyncSession, inspection: ProjectInspection) -> None:
    """Both anchors (spec 59): a worklog on one of the project's items, or an
    itemless one refined to the project. Seconds too — a number of entries says
    nothing about how much recorded time is about to vanish."""
    project_id = inspection.project.id
    row = (
        await session.execute(
            select(func.count(), func.coalesce(func.sum(Worklog.time_spent_seconds), 0)).where(
                or_(
                    Worklog.project_id == project_id,
                    Worklog.item_id.in_(select(WorkItem.id).where(WorkItem.project_id == project_id)),
                )
            )
        )
    ).one()
    inspection.add("worklogs", row[0])
    inspection.add("worklog_seconds", row[1])
