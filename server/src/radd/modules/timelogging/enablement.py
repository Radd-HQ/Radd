"""Per-project enablement — the gate that makes time logging opt-in per project."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError
from radd.modules.projects import service as projects_service

from .models import ProjectTimeLogging
from .schemas import ProjectTimeLoggingRead
from .types import TimelogEntity


async def is_enabled(session: AsyncSession, project_id: uuid.UUID) -> bool:
    config = await session.get(ProjectTimeLogging, project_id)
    return bool(config and config.enabled)


async def get_config(session: AsyncSession, project_id: uuid.UUID) -> ProjectTimeLoggingRead:
    # Validates the project exists; a missing row reads as disabled.
    await projects_service.get_project(session, project_id)
    config = await session.get(ProjectTimeLogging, project_id)
    return ProjectTimeLoggingRead(project_id=project_id, enabled=bool(config and config.enabled))


async def set_enabled(
    session: AsyncSession, project_id: uuid.UUID, enabled: bool
) -> ProjectTimeLoggingRead:
    await projects_service.get_project(session, project_id)
    config = await session.get(ProjectTimeLogging, project_id)
    if config is None:
        config = ProjectTimeLogging(project_id=project_id, enabled=enabled)
        session.add(config)
    else:
        config.enabled = enabled
    await session.flush()
    return ProjectTimeLoggingRead(project_id=project_id, enabled=config.enabled)


async def require_enabled(session: AsyncSession, project_id: uuid.UUID) -> None:
    """Guard writes — time logging must be turned on for the project first (409 if not)."""
    if not await is_enabled(session, project_id):
        raise ConflictError(
            TimelogEntity.PROJECT_CONFIG, reason="time logging is not enabled for this project"
        )
