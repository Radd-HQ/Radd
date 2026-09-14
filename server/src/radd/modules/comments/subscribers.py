"""Project teardown, this module's share (RADD-1174).

`projects` dispatches two in-transaction hooks and owns nothing here: INSPECTING
asks what of ours dies with the project (the confirmation dialog's numbers, and
the count the `project.deleted` event records), DELETING removes what the
database cannot cascade on its own. Registered at import, like the
`project.created` seeding hooks.
"""

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.hooks import hooks
from radd.modules.items.models import WorkItem
from radd.modules.projects.types import ProjectDeleting, ProjectHook, ProjectInspection

from .models import Comment
from .types import CommentParentType


def _on_project_items(project_id):
    """The polymorphic parent carries no FK (RADD-717), so the project's
    comments are reached through its items, not through a column."""
    return (
        Comment.entity_type == CommentParentType.ITEM.value,
        Comment.entity_id.in_(select(WorkItem.id).where(WorkItem.project_id == project_id)),
    )


@hooks.on(ProjectHook.INSPECTING)
async def count_comments(session: AsyncSession, inspection: ProjectInspection) -> None:
    inspection.add(
        "comments",
        await session.scalar(
            select(func.count()).select_from(Comment).where(*_on_project_items(inspection.project.id))
        ),
    )


@hooks.on(ProjectHook.DELETING)
async def delete_comments(session: AsyncSession, deleting: ProjectDeleting) -> None:
    await session.execute(delete(Comment).where(*_on_project_items(deleting.project.id)))
