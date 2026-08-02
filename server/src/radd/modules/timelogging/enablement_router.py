"""Per-project enablement endpoints — turn time logging on/off for a project."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser
from radd.modules.projects import service as projects_service

from . import enablement
from .schemas import ProjectTimeLoggingRead, ProjectTimeLoggingUpdate

router = APIRouter(prefix="/projects", tags=["timelogging"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/{project_id}/timelogging", response_model=ProjectTimeLoggingRead)
async def get_timelogging(
    project_id: uuid.UUID, session: Session, user: CurrentUser
) -> ProjectTimeLoggingRead:
    project = await projects_service.get_project(session, project_id)
    await authz.require(session, user, authz.Permission.ITEM_READ, project=project)
    return await enablement.get_config(session, project_id)


@router.put("/{project_id}/timelogging", response_model=ProjectTimeLoggingRead)
async def set_timelogging(
    project_id: uuid.UUID,
    data: ProjectTimeLoggingUpdate,
    session: Session,
    user: CurrentUser,
) -> ProjectTimeLoggingRead:
    project = await projects_service.get_project(session, project_id)
    await authz.require(session, user, authz.Permission.PROJECT_MANAGE, project=project)
    return await enablement.set_enabled(session, project_id, data.enabled)
