import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser
from radd.modules.projects import service as projects_service

from . import service
from .schemas import StateCreate, StateRead, StateUpdate

router = APIRouter(prefix="/states", tags=["workflow"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.post("", response_model=StateRead, status_code=201)
async def create_state(data: StateCreate, session: Session, user: CurrentUser) -> StateRead:
    project = await projects_service.get_project(session, data.project_id)
    await authz.require(session, user, authz.Permission.STATE_CREATE, project=project)
    return StateRead.model_validate(await service.create_state(session, data, actor_id=user.id))


@router.get("", response_model=list[StateRead])
async def list_states(
    session: Session,
    user: CurrentUser,
    project_id: uuid.UUID | None = None,
) -> list[StateRead]:
    """One project's states — or, unscoped, the states of every project the
    actor can read (the cross-project state-drag resolver on global board
    views needs the full set). Spec 86: the workspace_id scope is gone."""
    if project_id is not None:
        project = await projects_service.get_project(session, project_id)
        await authz.require(session, user, authz.Permission.ITEM_READ, project=project)
        return [StateRead.model_validate(s) for s in await service.list_states(session, project_id)]
    projects = await projects_service.list_projects(session)
    permissions = await authz.permissions_for_projects(session, user, projects)
    readable = [p.id for p in projects if authz.holds_base(permissions[p.id], authz.Permission.ITEM_READ)]
    return [
        StateRead.model_validate(s)
        for s in await service.states_for_projects(session, readable)
    ]


@router.patch("/{state_id}", response_model=StateRead)
async def update_state(
    state_id: uuid.UUID, data: StateUpdate, session: Session, user: CurrentUser
) -> StateRead:
    state = await service.get_state(session, state_id)
    project = await projects_service.get_project(session, state.project_id)
    await authz.require(session, user, authz.Permission.STATE_UPDATE, project=project)
    return StateRead.model_validate(
        await service.update_state(session, state_id, data, actor_id=user.id)
    )


@router.delete("/{state_id}", status_code=204)
async def delete_state(state_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    """Delete a workflow state (spec 87). 409 while it is the project default or
    any item still sits in it."""
    state = await service.get_state(session, state_id)
    project = await projects_service.get_project(session, state.project_id)
    await authz.require(session, user, authz.Permission.STATE_DELETE, project=project)
    await service.delete_state(session, state_id, actor_id=user.id)
