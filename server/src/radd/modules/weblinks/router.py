import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser
from radd.modules.items import service as items_service
from radd.modules.projects import service as projects_service

from . import service
from .schemas import WebLinkCreate, WebLinkRead, WebLinkUpdate

router = APIRouter(tags=["weblinks"])

Session = Annotated[AsyncSession, Depends(get_session)]


async def _require_item_perm(
    session: AsyncSession, user: CurrentUser, item_id: uuid.UUID, permission: authz.Permission
) -> None:
    # RADD-823: read-resolution goes through THE item seam, so this child
    # surface inherits per-item rules (relations) by construction; the write
    # atom layers on top of the same resolution.
    _item, project, _perms = await items_service.require_readable_item(session, item_id, user)
    if permission is not authz.Permission.ITEM_READ:
        await authz.require(session, user, permission, project=project)


@router.post("/items/{item_id}/web-links", response_model=WebLinkRead, status_code=201)
async def create_web_link(
    item_id: uuid.UUID, data: WebLinkCreate, session: Session, user: CurrentUser
) -> WebLinkRead:
    await _require_item_perm(session, user, item_id, authz.Permission.ITEM_UPDATE)
    return WebLinkRead.model_validate(
        await service.create_web_link(session, item_id, data, actor_id=user.id)
    )


@router.get("/items/{item_id}/web-links", response_model=list[WebLinkRead])
async def list_web_links(
    item_id: uuid.UUID, session: Session, user: CurrentUser
) -> list[WebLinkRead]:
    await _require_item_perm(session, user, item_id, authz.Permission.ITEM_READ)
    return [WebLinkRead.model_validate(link) for link in await service.list_for_item(session, item_id)]


@router.patch("/web-links/{link_id}", response_model=WebLinkRead)
async def update_web_link(
    link_id: uuid.UUID, data: WebLinkUpdate, session: Session, user: CurrentUser
) -> WebLinkRead:
    link = await service.get_web_link(session, link_id)
    await _require_item_perm(session, user, link.item_id, authz.Permission.ITEM_UPDATE)
    return WebLinkRead.model_validate(
        await service.update_web_link(session, link_id, data, actor_id=user.id)
    )


@router.delete("/web-links/{link_id}", status_code=204)
async def delete_web_link(link_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    link = await service.get_web_link(session, link_id)
    await _require_item_perm(session, user, link.item_id, authz.Permission.ITEM_UPDATE)
    await service.delete_web_link(session, link_id, actor_id=user.id)
