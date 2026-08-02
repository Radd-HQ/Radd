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
from .schemas import VcsLinkCreate, VcsLinkRead

router = APIRouter(tags=["vcs"])

Session = Annotated[AsyncSession, Depends(get_session)]


async def _require_item_perm(
    session: AsyncSession, user: CurrentUser, item_id: uuid.UUID, permission: authz.Permission
) -> None:
    item = await items_service.require_item(session, item_id)
    project = await projects_service.get_project(session, item.project_id)
    await authz.require(session, user, permission, project=project)


@router.post("/items/{item_id}/vcs-links", response_model=VcsLinkRead, status_code=201)
async def create_vcs_link(
    item_id: uuid.UUID, data: VcsLinkCreate, session: Session, user: CurrentUser
) -> VcsLinkRead:
    await _require_item_perm(session, user, item_id, authz.Permission.ITEM_UPDATE)
    return VcsLinkRead.model_validate(
        await service.link_vcs(session, item_id, data, actor_id=user.id)
    )


@router.get("/items/{item_id}/vcs-links", response_model=list[VcsLinkRead])
async def list_vcs_links(
    item_id: uuid.UUID, session: Session, user: CurrentUser
) -> list[VcsLinkRead]:
    await _require_item_perm(session, user, item_id, authz.Permission.ITEM_READ)
    return [
        VcsLinkRead.model_validate(link) for link in await service.list_for_item(session, item_id)
    ]


@router.delete("/vcs-links/{link_id}", status_code=204)
async def delete_vcs_link(link_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    link = await service.get_vcs_link(session, link_id)
    await _require_item_perm(session, user, link.item_id, authz.Permission.ITEM_UPDATE)
    await service.unlink_vcs(session, link_id, actor_id=user.id)
