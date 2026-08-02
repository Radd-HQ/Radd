from sqlalchemy.ext.asyncio import AsyncSession

from radd.hooks import hooks
from radd.modules.projects.models import Project
from radd.modules.projects.types import ProjectEvent

from . import defaults


@hooks.on(ProjectEvent.PROJECT_CREATED)
async def seed_builtin_views(session: AsyncSession, project: Project) -> None:
    """Every project ships with its Board/List/Planning/Roadmap as real,
    editable views (same in-txn idiom as workflow's default states)."""
    await defaults.seed_project_views(session, project)
