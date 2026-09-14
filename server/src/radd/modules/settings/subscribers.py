"""Project teardown, this module's share (RADD-1174).

`projects` dispatches two in-transaction hooks and owns nothing here: INSPECTING
asks what of ours dies with the project (the confirmation dialog's numbers, and
the count the `project.deleted` event records), DELETING removes what the
database cannot cascade on its own. Registered at import, like the
`project.created` seeding hooks.
"""

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from radd.hooks import hooks
from radd.modules.projects.types import ProjectDeleting, ProjectHook

from .models import ScopedSetting
from .types import SettingScope


@hooks.on(ProjectHook.DELETING)
async def delete_project_overrides(session: AsyncSession, deleting: ProjectDeleting) -> None:
    """`scope_id` is a bare uuid (no FK — the scope kinds are not one table), so
    a project's overrides would otherwise outlive it as unreachable rows."""
    await session.execute(
        delete(ScopedSetting).where(
            ScopedSetting.scope == SettingScope.PROJECT.value,
            ScopedSetting.scope_id == deleting.project.id,
        )
    )
