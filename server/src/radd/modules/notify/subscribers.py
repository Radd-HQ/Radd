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

from .models import NotificationRule
from .types import RuleScope


@hooks.on(ProjectHook.DELETING)
async def delete_project_subscriptions(session: AsyncSession, deleting: ProjectDeleting) -> None:
    """A subscription to the project (spec 118) names it by bare `scope_id`."""
    await session.execute(
        delete(NotificationRule).where(
            NotificationRule.scope == RuleScope.PROJECT.value,
            NotificationRule.scope_id == deleting.project.id,
        )
    )
