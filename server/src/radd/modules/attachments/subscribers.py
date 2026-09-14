"""Project teardown, this module's share (RADD-1174).

`projects` dispatches two in-transaction hooks and owns nothing here: INSPECTING
asks what of ours dies with the project (the confirmation dialog's numbers, and
the count the `project.deleted` event records), DELETING removes what the
database cannot cascade on its own. Registered at import, like the
`project.created` seeding hooks.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.hooks import hooks
from radd.modules.access import service as access_service
from radd.modules.items.models import WorkItem
from radd.modules.projects.types import ProjectDeleting, ProjectHook, ProjectInspection

from .acl import ATTACHMENT_RESOURCE
from .models import Attachment
from .service import _remove_bytes
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
    """Rows + grants in the transaction; bytes best-effort afterwards, the same
    split `delete_attachment` makes — an unreachable host must leave orphaned
    bytes rather than a project that cannot be deleted. The orphan GC consumer
    cannot do this one: it keys on `item.deleted`, and a purge emits none."""
    rows = list(
        (await session.execute(select(Attachment).where(*_on_project_items(deleting.project.id))))
        .scalars()
    )
    doomed = [(row.storage_host_id, row.storage_name) for row in rows]
    for row in rows:
        await access_service.clear_resource(session, ATTACHMENT_RESOURCE, str(row.id))
        await session.delete(row)
    await session.flush()
    for host_id, storage_name in doomed:
        await _remove_bytes(session, host_id, storage_name)
