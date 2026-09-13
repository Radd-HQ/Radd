"""Transition CRUD + the per-item allowed-transitions read (spec 61).

Reads share the states list's gating (item.read); writes ride STATE_MANAGE.
The item lookup is a deferred import — items loads after workflow (the same
request-time edge cycles has to items, documented in docs/modules.md).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.auth import authz
from radd.modules.auth.deps import Actor, CurrentUser
from radd.modules.projects import service as projects_service

from . import transitions
from .schemas import AllowedTransitions, TransitionCreate, TransitionRead, TransitionUpdate

router = APIRouter(tags=["workflow"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/projects/{project_id}/transitions", response_model=list[TransitionRead])
async def list_project_transitions(
    project_id: uuid.UUID, session: Session, user: CurrentUser
) -> list[TransitionRead]:
    project = await projects_service.get_project(session, project_id)
    await authz.require(session, user, authz.Permission.ITEM_READ, project=project)
    return [
        TransitionRead.model_validate(t)
        for t in await transitions.list_transitions(session, project_id)
    ]


@router.post("/transitions", response_model=TransitionRead, status_code=201)
async def create_transition(
    data: TransitionCreate, session: Session, user: CurrentUser
) -> TransitionRead:
    project = await projects_service.get_project(session, data.project_id)
    await authz.require(session, user, authz.Permission.STATE_MANAGE, project=project)
    return TransitionRead.model_validate(
        await transitions.create_transition(session, data, actor_id=user.id)
    )


@router.patch("/transitions/{transition_id}", response_model=TransitionRead)
async def update_transition(
    transition_id: uuid.UUID, data: TransitionUpdate, session: Session, user: CurrentUser
) -> TransitionRead:
    transition = await transitions.get_transition(session, transition_id)
    project = await projects_service.get_project(session, transition.project_id)
    await authz.require(session, user, authz.Permission.STATE_MANAGE, project=project)
    return TransitionRead.model_validate(
        await transitions.update_transition(session, transition_id, data, actor_id=user.id)
    )


@router.delete("/transitions/{transition_id}", status_code=204)
async def delete_transition(
    transition_id: uuid.UUID, session: Session, user: CurrentUser
) -> None:
    transition = await transitions.get_transition(session, transition_id)
    project = await projects_service.get_project(session, transition.project_id)
    await authz.require(session, user, authz.Permission.STATE_MANAGE, project=project)
    await transitions.delete_transition(session, transition_id, actor_id=user.id)


@router.get("/items/{item_id}/allowed-transitions", response_model=AllowedTransitions)
async def allowed_transitions_for_item(
    item_id: uuid.UUID, session: Session, user: Actor
) -> AllowedTransitions:
    from radd.modules.items import service as items_service  # deferred: items loads later

    item, project, _perms = await items_service.require_readable_item(session, item_id, user)
    return await transitions.allowed_transitions(session, project, item)
