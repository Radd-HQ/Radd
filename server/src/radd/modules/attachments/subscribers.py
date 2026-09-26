"""Project teardown (RADD-1174): attachments on the project's items die with it."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.hooks import hooks
from radd.modules.items.models import WorkItem
from radd.modules.projects.types import ProjectDeleting, ProjectHook, ProjectInspection

from .models import Attachment
from .service import purge, remove_bytes
from .types import AttachmentParentType


def _on_project_items(project_id):
    return (
        Attachment.entity_type == AttachmentParentType.ITEM.value,
        Attachment.entity_id.in_(select(WorkItem.id).where(WorkItem.project_id == project_id)),
    )


@hooks.on(ProjectHook.INSPECTING)
async def count_attachments(session: AsyncSession, inspection: ProjectInspection) -> None:
    inspection.add(
        "attachments",
        await session.scalar(
            select(func.count())
            .select_from(Attachment)
            .where(*_on_project_items(inspection.project.id))
        ),
    )


@hooks.on(ProjectHook.DELETING)
async def delete_attachments(session: AsyncSession, deleting: ProjectDeleting) -> None:
    """Rows + grants in the transaction, bytes best-effort afterwards. The parent
    cascade cannot do this one: it keys on `item.deleted`, which a purge does not emit."""
    rows = list(
        (await session.execute(select(Attachment).where(*_on_project_items(deleting.project.id))))
        .scalars()
    )
    doomed = await purge(session, rows)
    await session.flush()
    await remove_bytes(session, doomed)
