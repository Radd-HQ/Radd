import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser
from radd.modules.projects import service as projects_service

from . import service
from .schemas import EffectiveScreen, ScreenRead, ScreenReplace

router = APIRouter(prefix="/screens", tags=["screens"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/effective", response_model=EffectiveScreen)
async def effective_screen(
    project_id: uuid.UUID,
    session: Session,
    user: CurrentUser,
    issue_type_id: uuid.UUID | None = None,
) -> EffectiveScreen:
    """The resolved field layout for an item's (project, issue-type) — what the issue
    view renders. `item.read` on the project."""
    project = await projects_service.get_project(session, project_id)
    await authz.require(session, user, authz.Permission.ITEM_READ, project=project)
    return await service.resolve_effective(session, project, issue_type_id)


@router.get("", response_model=ScreenRead)
async def get_screen(
    project_id: uuid.UUID,
    session: Session,
    user: CurrentUser,
    issue_type_id: uuid.UUID | None = None,
) -> ScreenRead:
    """A scope's stored screen (for the editor). `project.manage`."""
    project = await projects_service.get_project(session, project_id)
    await authz.require(session, user, authz.Permission.PROJECT_MANAGE, project=project)
    return await service.get_screen_config(session, project_id, issue_type_id)


@router.put("", response_model=ScreenRead)
async def replace_screen(
    data: ScreenReplace, session: Session, user: CurrentUser
) -> ScreenRead:
    """Full-list replace of one scope's layout (empty list clears it). `project.manage`."""
    project = await projects_service.get_project(session, data.project_id)
    await authz.require(session, user, authz.Permission.PROJECT_MANAGE, project=project)
    return await service.replace_screen(
        session, project, data.issue_type_id, data.fields, actor_id=user.id
    )
