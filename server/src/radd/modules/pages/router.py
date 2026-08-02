import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser
from radd.modules.items import service as items_service
from radd.modules.projects import service as projects_service

from . import links, search, service, spaces
from .models import Page
from .schemas import (
    DocLinkCreate,
    PageLinkedItem,
    PageCreate,
    PageRead,
    PageSummary,
    PageUpdate,
    DocRestoreRequest,
    PageSearchResponse,
    PageSpaceCreate,
    PageSpaceRead,
    PageSpaceUpdate,
    PageVersionMeta,
    PageVersionRead,
    ItemPageRef,
)

router = APIRouter(tags=["pages"])

Session = Annotated[AsyncSession, Depends(get_session)]


async def _page_guard(
    session: AsyncSession, user, page_id: uuid.UUID, permission: authz.Permission
) -> Page:
    """Resolve a page and enforce a global doc permission."""
    page = await service.get_page(session, page_id)
    await authz.require(session, user, permission)
    return page


# --- spaces ---


@router.get("/page-spaces", response_model=list[PageSpaceRead])
async def list_spaces(session: Session, user: CurrentUser) -> list[PageSpaceRead]:
    await authz.require(session, user, authz.Permission.PAGE_READ)
    return await spaces.list_spaces(session)


@router.post("/page-spaces", response_model=PageSpaceRead, status_code=201)
async def create_space(
    data: PageSpaceCreate, session: Session, user: CurrentUser
) -> PageSpaceRead:
    await authz.require(session, user, authz.Permission.PAGE_MANAGE)
    return PageSpaceRead.model_validate(await spaces.create_space(session, data, user.id))


@router.patch("/page-spaces/{space_id}", response_model=PageSpaceRead)
async def update_space(
    space_id: uuid.UUID, data: PageSpaceUpdate, session: Session, user: CurrentUser
) -> PageSpaceRead:
    space = await spaces.get_space(session, space_id)
    await authz.require(session, user, authz.Permission.PAGE_MANAGE)
    return PageSpaceRead.model_validate(await spaces.update_space(session, space_id, data, user.id))


@router.delete("/page-spaces/{space_id}", status_code=204)
async def delete_space(
    space_id: uuid.UUID, session: Session, user: CurrentUser, force: bool = False
) -> None:
    space = await spaces.get_space(session, space_id)
    await authz.require(session, user, authz.Permission.PAGE_MANAGE)
    await spaces.delete_space(session, space_id, force=force, actor_id=user.id)


# --- pages ---


@router.get("/page-spaces/{space_id}/pages", response_model=list[PageSummary])
async def list_pages(
    space_id: uuid.UUID,
    session: Session,
    user: CurrentUser,
    include_archived: bool = False,
) -> list[PageSummary]:
    space = await spaces.get_space(session, space_id)
    permission = (
        authz.Permission.PAGE_MANAGE if include_archived else authz.Permission.PAGE_READ
    )
    await authz.require(session, user, permission)
    return await service.list_pages(session, space_id, include_archived=include_archived)


@router.post("/pages", response_model=PageRead, status_code=201)
async def create_page(data: PageCreate, session: Session, user: CurrentUser) -> PageRead:
    space = await spaces.get_space(session, data.space_id)
    await authz.require(session, user, authz.Permission.PAGE_WRITE)
    page = await service.create_page(session, data, user.id)
    return await service.page_read(session, page)


@router.get("/pages/{page_id}", response_model=PageRead)
async def get_page(page_id: uuid.UUID, session: Session, user: CurrentUser) -> PageRead:
    page = await _page_guard(session, user, page_id, authz.Permission.PAGE_READ)
    return await service.page_read(session, page)


@router.patch("/pages/{page_id}", response_model=PageRead)
async def update_page(
    page_id: uuid.UUID, data: PageUpdate, session: Session, user: CurrentUser
) -> PageRead:
    await _page_guard(session, user, page_id, authz.Permission.PAGE_WRITE)
    page = await service.update_page(session, page_id, data, user.id)
    return await service.page_read(session, page)


@router.delete("/pages/{page_id}", status_code=204)
async def delete_page(
    page_id: uuid.UUID, session: Session, user: CurrentUser, hard: bool = False
) -> None:
    # spec 50: hard-delete is its own atom (page.delete, implied by page.manage).
    permission = authz.Permission.PAGE_DELETE if hard else authz.Permission.PAGE_WRITE
    await _page_guard(session, user, page_id, permission)
    if hard:
        await service.hard_delete_page(session, page_id, user.id)
    else:
        await service.archive_page(session, page_id, user.id)


@router.post("/pages/{page_id}/unarchive", response_model=PageRead)
async def unarchive_page(
    page_id: uuid.UUID, session: Session, user: CurrentUser
) -> PageRead:
    await _page_guard(session, user, page_id, authz.Permission.PAGE_MANAGE)
    page = await service.unarchive_page(session, page_id, user.id)
    return await service.page_read(session, page)


# --- versions ---


@router.get("/pages/{page_id}/versions", response_model=list[PageVersionMeta])
async def list_versions(
    page_id: uuid.UUID, session: Session, user: CurrentUser
) -> list[PageVersionMeta]:
    await _page_guard(session, user, page_id, authz.Permission.PAGE_READ)
    return [PageVersionMeta.model_validate(v) for v in await service.list_versions(session, page_id)]


@router.get("/pages/{page_id}/versions/{version}", response_model=PageVersionRead)
async def get_version(
    page_id: uuid.UUID, version: int, session: Session, user: CurrentUser
) -> PageVersionRead:
    await _page_guard(session, user, page_id, authz.Permission.PAGE_READ)
    return PageVersionRead.model_validate(await service.get_version(session, page_id, version))


@router.post("/pages/{page_id}/restore", response_model=PageRead)
async def restore_version(
    page_id: uuid.UUID, data: DocRestoreRequest, session: Session, user: CurrentUser
) -> PageRead:
    await _page_guard(session, user, page_id, authz.Permission.PAGE_WRITE)
    page = await service.restore_version(session, page_id, data.version, user.id)
    return await service.page_read(session, page)


# --- issue links ---


@router.get("/pages/{page_id}/items", response_model=list[PageLinkedItem])
async def linked_items(
    page_id: uuid.UUID, session: Session, user: CurrentUser
) -> list[PageLinkedItem]:
    await _page_guard(session, user, page_id, authz.Permission.PAGE_READ)
    return await links.linked_items(session, page_id, user)


@router.post("/pages/{page_id}/items", response_model=PageLinkedItem, status_code=201)
async def link_item(
    page_id: uuid.UUID, data: DocLinkCreate, session: Session, user: CurrentUser
) -> PageLinkedItem:
    await _page_guard(session, user, page_id, authz.Permission.PAGE_WRITE)
    return await links.link_item(session, page_id, data.item_key, user)


@router.delete("/pages/{page_id}/items/{item_id}", status_code=204)
async def unlink_item(
    page_id: uuid.UUID, item_id: uuid.UUID, session: Session, user: CurrentUser
) -> None:
    await _page_guard(session, user, page_id, authz.Permission.PAGE_WRITE)
    await links.unlink_item(session, page_id, item_id, user.id)


@router.get("/items/{item_id}/pages", response_model=list[ItemPageRef])
async def item_docs(item_id: uuid.UUID, session: Session, user: CurrentUser) -> list[ItemPageRef]:
    """Pages linked to an item — path-extends the items surface (like timelogging)."""
    item = await items_service.require_item(session, item_id)
    project = await projects_service.get_project(session, item.project_id)
    await authz.require(session, user, authz.Permission.ITEM_READ, project=project)
    return await links.pages_for_item(session, item_id)


# --- search ---


@router.get("/pages/search", response_model=PageSearchResponse)
async def search_docs(
    q: str, session: Session, user: CurrentUser, limit: int = 20
) -> PageSearchResponse:
    await authz.require(session, user, authz.Permission.PAGE_READ)
    limit = max(1, min(limit, 50))
    return PageSearchResponse(
        results=await search.search_pages(session, q, limit=limit)
    )
