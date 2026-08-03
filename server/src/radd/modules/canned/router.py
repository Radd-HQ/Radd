import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.auth import authz
from radd.modules.auth.authz import Permission
from radd.modules.auth.deps import CurrentUser
from radd.modules.items import service as items_service
from radd.modules.projects import service as projects_service

from . import service
from .render import render_canned
from .schemas import (
    CannedRenderResult,
    CannedResponseCreate,
    CannedResponseRead,
    CannedResponseUpdate,
)

router = APIRouter(tags=["canned"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/canned-responses", response_model=list[CannedResponseRead])
async def list_responses(session: Session, user: CurrentUser) -> list[CannedResponseRead]:
    # Any member may read (they insert these while replying) — the floor is
    # item.read in SOME project (RADD-788), not the global atom.
    if not await authz.readable_projects(session, user):
        return []
    return [
        CannedResponseRead.model_validate(response)
        for response in await service.list_responses(session)
    ]


@router.get("/canned-responses/{response_id}/render", response_model=CannedRenderResult)
async def render_response(
    response_id: uuid.UUID, item_id: uuid.UUID, session: Session, user: CurrentUser
) -> CannedRenderResult:
    """The body with its `{{token}}` variables resolved against `item_id`
    (spec 66) — `me` is the caller; unresolved tokens stay verbatim."""
    response = await service.get_response(session, response_id)
    item = await items_service.require_item(session, item_id)
    project = await projects_service.get_project(session, item.project_id)
    await authz.require(session, user, Permission.ITEM_READ, project=project)
    ctx = await service.render_context(session, item, project, me=user)
    return CannedRenderResult(body=render_canned(response.body, ctx))


@router.post("/canned-responses", response_model=CannedResponseRead, status_code=201)
async def create_response(
    data: CannedResponseCreate, session: Session, user: CurrentUser
) -> CannedResponseRead:
    await authz.require(session, user, Permission.CANNED_CREATE)
    return CannedResponseRead.model_validate(
        await service.create_response(session, data, actor_id=user.id)
    )


@router.patch("/canned-responses/{response_id}", response_model=CannedResponseRead)
async def update_response(
    response_id: uuid.UUID, data: CannedResponseUpdate, session: Session, user: CurrentUser
) -> CannedResponseRead:
    response = await service.get_response(session, response_id)
    await authz.require(
        session, user, Permission.CANNED_UPDATE
    )
    return CannedResponseRead.model_validate(
        await service.update_response(session, response_id, data, actor_id=user.id)
    )


@router.delete("/canned-responses/{response_id}", status_code=204)
async def delete_response(
    response_id: uuid.UUID, session: Session, user: CurrentUser
) -> None:
    response = await service.get_response(session, response_id)
    await authz.require(
        session, user, Permission.CANNED_DELETE
    )
    await service.delete_response(session, response_id, actor_id=user.id)
