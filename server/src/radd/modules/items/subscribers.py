"""Project teardown hooks (RADD-1174) — the contract is on `projects.types.ProjectHook`."""

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from radd.hooks import hooks
from radd.modules.projects.types import ProjectDeleting, ProjectHook, ProjectInspection

from .models import WorkItem


@hooks.on(ProjectHook.INSPECTING)
async def count_items(session: AsyncSession, inspection: ProjectInspection) -> None:
    inspection.add(
        "items",
        await session.scalar(
            select(func.count()).select_from(WorkItem).where(WorkItem.project_id == inspection.project.id)
        ),
    )


@hooks.on(ProjectHook.DELETING)
async def detach_foreign_children(session: AsyncSession, deleting: ProjectDeleting) -> None:
    """`work_items.parent_id` has no ON DELETE action. Children INSIDE the
    project die in the same statement as their parents (NO ACTION is checked at
    statement end), but a child that was moved to another project keeps
    pointing here and would block the purge — it becomes a top-level item,
    which is what re-parenting to none means everywhere else."""
    project_id = deleting.project.id
    await session.execute(
        update(WorkItem)
        .where(
            WorkItem.parent_id.in_(select(WorkItem.id).where(WorkItem.project_id == project_id)),
            WorkItem.project_id != project_id,
        )
        .values(parent_id=None)
    )
