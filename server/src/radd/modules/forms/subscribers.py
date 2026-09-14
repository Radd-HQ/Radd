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
from radd.modules.projects.types import ProjectHook, ProjectInspection

from .models import Form


@hooks.on(ProjectHook.INSPECTING)
async def count_forms(session: AsyncSession, inspection: ProjectInspection) -> None:
    inspection.add(
        "forms",
        await session.scalar(
            select(func.count()).select_from(Form).where(Form.project_id == inspection.project.id)
        ),
    )
