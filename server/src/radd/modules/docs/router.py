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
from .models import DocPage
from .schemas import (
    DocLinkCreate,
    DocLinkedItem,
    DocPageCreate,
    DocPageRead,
    DocPageSummary,
    DocPageUpdate,
    DocRestoreRequest,
    DocSearchResponse,
    DocSpaceCreate,
    DocSpaceRead,
    DocSpaceUpdate,
    DocVersionMeta,
    DocVersionRead,
    ItemDocRef,
)

router = APIRouter(tags=["docs"])

Session = Annotated[AsyncSession, Depends(get_session)]


async def _page_guard(
    session: AsyncSession, user, page_id: uuid.UUID, permission: authz.Permission
) -> DocPage:
    """Resolve a page and enforce a global doc permission."""
    page = await service.get_page(session, page_id)
    await authz.require(session, user, permission)
    return page


# --- spaces ---


@router.get("/doc-spaces", response_model=list[DocSpaceRead])
async def list_spaces(session: Session, user: CurrentUser) -> list[DocSpaceRead]:
    await authz.require(session, user, authz.Permission.DOC_READ)
    return await spaces.list_spaces(session)


@router.post("/doc-spaces", response_model=DocSpaceRead, status_code=201)
async def create_space(
    data: DocSpaceCreate, session: Session, user: CurrentUser
) -> DocSpaceRead:
    await authz.require(session, user, authz.Permission.DOC_MANAGE)
    return DocSpaceRead.model_validate(await spaces.create_space(session, data, user.id))


@router.patch("/doc-spaces/{space_id}", response_model=DocSpaceRead)
async def update_space(
    space_id: uuid.UUID, data: DocSpaceUpdate, session: Session, user: CurrentUser
) -> DocSpaceRead:
    space = await spaces.get_space(session, space_id)
    await authz.require(session, user, authz.Permission.DOC_MANAGE)
    return DocSpaceRead.model_validate(await spaces.update_space(session, space_id, data, user.id))


@router.delete("/doc-spaces/{space_id}", status_code=204)
async def delete_space(
    space_id: uuid.UUID, session: Session, user: CurrentUser, force: bool = False
) -> None:
    space = await spaces.get_space(session, space_id)
    await authz.require(session, user, authz.Permission.DOC_MANAGE)
    await spaces.delete_space(session, space_id, force=force, actor_id=user.id)


# --- pages ---


@router.get("/doc-spaces/{space_id}/pages", response_model=list[DocPageSummary])
async def list_pages(
    space_id: uuid.UUID,
    session: Session,
    user: CurrentUser,
    include_archived: bool = False,
) -> list[DocPageSummary]:
    space = await spaces.get_space(session, space_id)
    permission = (
        authz.Permission.DOC_MANAGE if include_archived else authz.Permission.DOC_READ
    )
    await authz.require(session, user, permission)
    return await service.list_pages(session, space_id, include_archived=include_archived)


@router.post("/doc-pages", response_model=DocPageRead, status_code=201)
async def create_page(data: DocPageCreate, session: Session, user: CurrentUser) -> DocPageRead:
    space = await spaces.get_space(session, data.space_id)
    await authz.require(session, user, authz.Permission.DOC_WRITE)
    page = await service.create_page(session, data, user.id)
    return await service.page_read(session, page)


@router.get("/doc-pages/{page_id}", response_model=DocPageRead)
async def get_page(page_id: uuid.UUID, session: Session, user: CurrentUser) -> DocPageRead:
    page = await _page_guard(session, user, page_id, authz.Permission.DOC_READ)
    return await service.page_read(session, page)


@router.patch("/doc-pages/{page_id}", response_model=DocPageRead)
async def update_page(
    page_id: uuid.UUID, data: DocPageUpdate, session: Session, user: CurrentUser
) -> DocPageRead:
    await _page_guard(session, user, page_id, authz.Permission.DOC_WRITE)
    page = await service.update_page(session, page_id, data, user.id)
    return await service.page_read(session, page)


@router.delete("/doc-pages/{page_id}", status_code=204)
async def delete_page(
    page_id: uuid.UUID, session: Session, user: CurrentUser, hard: bool = False
) -> None:
    # spec 50: hard-delete is its own atom (doc.delete, implied by doc.manage).
    permission = authz.Permission.DOC_DELETE if hard else authz.Permission.DOC_WRITE
    await _page_guard(session, user, page_id, permission)
    if hard:
        await service.hard_delete_page(session, page_id, user.id)
    else:
        await service.archive_page(session, page_id, user.id)


@router.post("/doc-pages/{page_id}/unarchive", response_model=DocPageRead)
async def unarchive_page(
    page_id: uuid.UUID, session: Session, user: CurrentUser
) -> DocPageRead:
    await _page_guard(session, user, page_id, authz.Permission.DOC_MANAGE)
    page = await service.unarchive_page(session, page_id, user.id)
    return await service.page_read(session, page)


# --- versions ---


@router.get("/doc-pages/{page_id}/versions", response_model=list[DocVersionMeta])
async def list_versions(
    page_id: uuid.UUID, session: Session, user: CurrentUser
) -> list[DocVersionMeta]:
    await _page_guard(session, user, page_id, authz.Permission.DOC_READ)
    return [DocVersionMeta.model_validate(v) for v in await service.list_versions(session, page_id)]


@router.get("/doc-pages/{page_id}/versions/{version}", response_model=DocVersionRead)
async def get_version(
    page_id: uuid.UUID, version: int, session: Session, user: CurrentUser
) -> DocVersionRead:
    await _page_guard(session, user, page_id, authz.Permission.DOC_READ)
    return DocVersionRead.model_validate(await service.get_version(session, page_id, version))


@router.post("/doc-pages/{page_id}/restore", response_model=DocPageRead)
async def restore_version(
    page_id: uuid.UUID, data: DocRestoreRequest, session: Session, user: CurrentUser
) -> DocPageRead:
    await _page_guard(session, user, page_id, authz.Permission.DOC_WRITE)
    page = await service.restore_version(session, page_id, data.version, user.id)
    return await service.page_read(session, page)


# --- issue links ---


@router.get("/doc-pages/{page_id}/items", response_model=list[DocLinkedItem])
async def linked_items(
    page_id: uuid.UUID, session: Session, user: CurrentUser
) -> list[DocLinkedItem]:
    await _page_guard(session, user, page_id, authz.Permission.DOC_READ)
    return await links.linked_items(session, page_id, user)


@router.post("/doc-pages/{page_id}/items", response_model=DocLinkedItem, status_code=201)
async def link_item(
    page_id: uuid.UUID, data: DocLinkCreate, session: Session, user: CurrentUser
) -> DocLinkedItem:
    await _page_guard(session, user, page_id, authz.Permission.DOC_WRITE)
    return await links.link_item(session, page_id, data.item_key, user)


@router.delete("/doc-pages/{page_id}/items/{item_id}", status_code=204)
async def unlink_item(
    page_id: uuid.UUID, item_id: uuid.UUID, session: Session, user: CurrentUser
) -> None:
    await _page_guard(session, user, page_id, authz.Permission.DOC_WRITE)
    await links.unlink_item(session, page_id, item_id, user.id)


@router.get("/items/{item_id}/docs", response_model=list[ItemDocRef])
async def item_docs(item_id: uuid.UUID, session: Session, user: CurrentUser) -> list[ItemDocRef]:
    """Pages linked to an item — path-extends the items surface (like timelogging)."""
    item = await items_service.require_item(session, item_id)
    project = await projects_service.get_project(session, item.project_id)
    await authz.require(session, user, authz.Permission.ITEM_READ, project=project)
    return await links.pages_for_item(session, item_id)


# --- search ---


@router.get("/docs/search", response_model=DocSearchResponse)
async def search_docs(
    q: str, session: Session, user: CurrentUser, limit: int = 20
) -> DocSearchResponse:
    await authz.require(session, user, authz.Permission.DOC_READ)
    limit = max(1, min(limit, 50))
    return DocSearchResponse(
        results=await search.search_pages(session, q, limit=limit)
    )
