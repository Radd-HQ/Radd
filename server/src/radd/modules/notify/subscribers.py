"""Project teardown (RADD-1174): subscriptions naming the project die with it."""

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
