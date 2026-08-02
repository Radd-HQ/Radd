from sqlalchemy.ext.asyncio import AsyncSession

from radd.hooks import hooks
from radd.modules.projects.models import Project
from radd.modules.projects.types import ProjectEvent

from . import service


@hooks.on(ProjectEvent.PROJECT_CREATED)
async def seed_default_states(session: AsyncSession, project: Project) -> None:
    await service.create_default_states(session, project)
