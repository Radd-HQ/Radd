import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.kernel.registry import registries
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser
from radd.modules.items import service as items_service
from radd.modules.projects import service as projects_service

from . import (
    access,
    page_access,
    backlinks,
    export as page_export,
    labels as page_labels,
    links,
    search,
    service,
    spaces,
    templates as page_templates,
    watchers as page_watchers,
)
from radd.exceptions import NotFoundError

from .models import Page, PageTemplate
from radd.modules.access.types import Access
from .types import PageEntity
from .schemas import (
    DocLinkCreate,
    PageLinkedItem,
    PageBacklink,
    PageCreate,
    PageLabelled,
    PageLabelsUpdate,
    PageTemplateCreate,
    PageTemplateRead,
    PageTemplateUpdate,
    PageExtensionRead,
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
    """Resolve a page and enforce the atom IN ITS SPACE (RADD-791).

    The single edit that rescopes most of this router: ~20 endpoints go through
    here, and they were all asking a global question about a page that lives
    somewhere. `page.space_id` is the scope, so a role granted on one space
    reaches its pages and no others.
    """
    page = await service.get_page(session, page_id)
    await authz.require(session, user, permission, space_id=page.space_id)
    # ...then the page's OWN restriction, which can only narrow (RADD-792).
    wanted = Access.WRITE.value if permission is not authz.Permission.PAGE_READ else Access.READ.value
    if not await page_access.page_access(session, user, page, wanted):
        raise NotFoundError(PageEntity.PAGE, page_id)
    return page


# --- spaces ---


@router.get("/page-spaces", response_model=list[PageSpaceRead])
async def list_spaces(session: Session, user: CurrentUser) -> list[PageSpaceRead]:
    """The spaces this actor may read (RADD-791) — an empty list, never a 403.

    Same rule as `readable_projects`: being entitled to no space is not doing
    anything wrong, so the wiki nav renders empty instead of greeting a new
    account with a permission toast.
    """
    readable = await access.readable_spaces(session, user)
    out = []
    for space in await spaces.list_spaces(session):
        if space.id not in readable:
            continue
        # RADD-814: each row carries the caller's per-space union, so the SPA's
        # `can()` resolves space-scoped atoms against THE space (RADD-810 class).
        space.permissions = sorted(str(p) for p in readable[space.id])
        out.append(space)
    return out


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
    await authz.require(session, user, authz.Permission.PAGE_MANAGE, space_id=space.id)
    return PageSpaceRead.model_validate(await spaces.update_space(session, space_id, data, user.id))


@router.delete("/page-spaces/{space_id}", status_code=204)
async def delete_space(
    space_id: uuid.UUID, session: Session, user: CurrentUser, force: bool = False
) -> None:
    space = await spaces.get_space(session, space_id)
    await authz.require(session, user, authz.Permission.PAGE_MANAGE, space_id=space.id)
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
    await authz.require(session, user, permission, space_id=space.id)
    return await service.list_pages(
        session, space_id, include_archived=include_archived, actor=user
    )


@router.post("/pages", response_model=PageRead, status_code=201)
async def create_page(data: PageCreate, session: Session, user: CurrentUser) -> PageRead:
    space = await spaces.get_space(session, data.space_id)
    await authz.require(session, user, authz.Permission.PAGE_WRITE, space_id=space.id)
    page = await service.create_page(session, data, user.id)
    return await service.page_read(session, page)


@router.get("/page-templates", response_model=list[PageTemplateRead])
async def list_templates(
    session: Session, user: CurrentUser, space_id: uuid.UUID | None = None
) -> list[PageTemplateRead]:
    """Templates usable here: the space's own, plus the global ones (RADD-712)."""
    if space_id is not None:
        await authz.require(session, user, authz.Permission.PAGE_READ, space_id=space_id)
    elif not await access.readable_spaces(session, user):
        return []
    return [
        PageTemplateRead.model_validate(t)
        for t in await page_templates.list_templates(session, space_id)
    ]


@router.post("/page-templates", response_model=PageTemplateRead, status_code=201)
async def create_template(
    data: PageTemplateCreate, session: Session, user: CurrentUser
) -> PageTemplateRead:
    await authz.require(session, user, authz.Permission.PAGE_MANAGE)
    row = PageTemplate(**data.model_dump(), created_by=user.id)
    session.add(row)
    await session.flush()
    return PageTemplateRead.model_validate(row)


@router.patch("/page-templates/{template_id}", response_model=PageTemplateRead)
async def update_template(
    template_id: uuid.UUID, data: PageTemplateUpdate, session: Session, user: CurrentUser
) -> PageTemplateRead:
    await authz.require(session, user, authz.Permission.PAGE_MANAGE)
    row = await session.get(PageTemplate, template_id)
    if row is None:
        raise NotFoundError(PageEntity.PAGE, template_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    await session.flush()
    return PageTemplateRead.model_validate(row)


@router.delete("/page-templates/{template_id}", status_code=204)
async def delete_template(
    template_id: uuid.UUID, session: Session, user: CurrentUser
) -> None:
    await authz.require(session, user, authz.Permission.PAGE_MANAGE)
    row = await session.get(PageTemplate, template_id)
    if row is not None:
        await session.delete(row)
        await session.flush()


@router.get("/pages/extensions", response_model=list[PageExtensionRead])
async def list_page_extensions(session: Session, user: CurrentUser) -> list[PageExtensionRead]:
    """What the editor's insert menu offers (RADD-709).

    Registered BEFORE `/pages/{page_id}` for the same reason `by-path` is: a
    literal segment declared after a UUID path would never be reached.

    Read from the kernel registry rather than a constant, so a plugin's
    extension appears here the moment it mounts and disappears when it is
    disabled — which is the whole point of the registry.
    """
    # Extension DESCRIPTORS are instance-wide, not a space's content: the floor
    # is "may read some space at all" (RADD-791).
    if not await access.readable_spaces(session, user):
        return []
    sources = registries.page_extension_sources
    return [
        PageExtensionRead(
            name=spec.name,
            label=spec.label,
            description=spec.description,
            params_schema=spec.params_schema,
            icon=spec.icon,
            source=(source.plugin if (source := sources.get(spec.name)) else ""),
        )
        for spec in sorted(registries.page_extensions.values(), key=lambda s: s.label)
    ]


@router.get("/pages/by-path/{space_slug}/{page_slug}", response_model=PageRead)
async def get_page_by_path(
    space_slug: str, page_slug: str, session: Session, user: CurrentUser
) -> PageRead:
    """`/pages/<space>/<page>` (RADD-702). Registered BEFORE `/pages/{page_id}`
    so `by-path` is never parsed as a UUID. Either segment may be an id, which
    is what lets a pre-702 UUID link resolve and redirect instead of rotting."""
    page = await service.resolve_page_by_slug(session, space_slug, page_slug)
    # Resolve FIRST, then check the space it turned out to live in — a slug pair
    # is not a permission, and checking before the lookup would have been the
    # global question again. Then the page's own restriction (RADD-792); a
    # restricted page 404s rather than 403ing, so its EXISTENCE stays private.
    await authz.require(session, user, authz.Permission.PAGE_READ, space_id=page.space_id)
    if not await page_access.page_access(session, user, page):
        raise NotFoundError(PageEntity.PAGE, page.id)
    return await service.page_read(session, page)


@router.get("/pages/search", response_model=PageSearchResponse)
async def search_docs(
    q: str, session: Session, user: CurrentUser, limit: int = 20
) -> PageSearchResponse:
    """Also BEFORE `/pages/{page_id}`, and for the same reason as `by-path`.

    FastAPI matches in DECLARATION order, so a literal that shares a shape with
    an earlier `{param}` route is simply never reached. RADD-701 moved this here
    from `/docs/search` and left it at the bottom of the file, where
    `/pages/search` parsed as `page_id="search"` and answered 422 — a route that
    exists, is registered, appears in the OpenAPI schema, and cannot be called
    (RADD-761). Anything added as `/pages/<literal>` belongs in this block.
    """
    readable = await access.readable_spaces(session, user)
    if not readable:
        return PageSearchResponse(results=[])
    limit = max(1, min(limit, 50))
    results = await search.search_pages(session, q, limit=limit, space_ids=set(readable))
    # A restricted page's TITLE is usually the sensitive part, so a search hit
    # would defeat the restriction on its own (RADD-792).
    return PageSearchResponse(
        results=await service.drop_restricted_results(session, user, results)
    )


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


@router.get("/page-spaces/{space_id}/export")
async def export_space(space_id: uuid.UUID, session: Session, user: CurrentUser) -> Response:
    """A whole space as a zip of markdown (RADD-721)."""
    space = await spaces.get_space(session, space_id)
    await authz.require(session, user, authz.Permission.PAGE_READ, space_id=space.id)
    name, blob = await page_export.export_zip(session, space)
    return _zip_response(name, blob)


@router.get("/pages/{page_id}/export")
async def export_page(page_id: uuid.UUID, session: Session, user: CurrentUser) -> Response:
    """One page and everything beneath it, as a zip of markdown."""
    page = await _page_guard(session, user, page_id, authz.Permission.PAGE_READ)
    space = await spaces.get_space(session, page.space_id)
    name, blob = await page_export.export_zip(session, space, root=page)
    return _zip_response(name, blob)


def _zip_response(name: str, blob: bytes) -> Response:
    return Response(
        content=blob,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/pages/by-label/{name}", response_model=list[PageLabelled])
async def pages_by_label(
    name: str, session: Session, user: CurrentUser, space: str = ""
) -> list[PageLabelled]:
    """Every page carrying a label (RADD-718) — the "content by label" pattern
    that lets an index page maintain itself. Declared before `/pages/{page_id}`
    so the literal segment is reachable."""
    readable = await access.readable_spaces(session, user)
    if not readable:
        return []
    rows = await page_labels.pages_with_label(
        session, name, space_slug=space, space_ids=set(readable)
    )
    return await service.drop_restricted_labelled(session, user, rows)


@router.put("/pages/{page_id}/labels", response_model=list[str])
async def set_page_labels(
    page_id: uuid.UUID, data: PageLabelsUpdate, session: Session, user: CurrentUser
) -> list[str]:
    await _page_guard(session, user, page_id, authz.Permission.PAGE_WRITE)
    labels = await page_labels.set_labels(session, page_id, data.labels, user.id)
    return [label.name for label in labels]


@router.get("/pages/{page_id}/watch")
async def get_watch(page_id: uuid.UUID, session: Session, user: CurrentUser) -> dict[str, bool]:
    await _page_guard(session, user, page_id, authz.Permission.PAGE_READ)
    return {"watching": await page_watchers.is_watching(session, page_id, user.id)}


@router.put("/pages/{page_id}/watch")
async def set_watch(page_id: uuid.UUID, session: Session, user: CurrentUser) -> dict[str, bool]:
    """Watch a page (RADD-719). Idempotent — watching twice is a double click."""
    await _page_guard(session, user, page_id, authz.Permission.PAGE_READ)
    await page_watchers.watch(session, page_id, user.id)
    return {"watching": True}


@router.delete("/pages/{page_id}/watch")
async def clear_watch(page_id: uuid.UUID, session: Session, user: CurrentUser) -> dict[str, bool]:
    await _page_guard(session, user, page_id, authz.Permission.PAGE_READ)
    await page_watchers.unwatch(session, page_id, user.id)
    return {"watching": False}


@router.get("/pages/{page_id}/backlinks", response_model=list[PageBacklink])
async def list_backlinks(
    page_id: uuid.UUID, session: Session, user: CurrentUser
) -> list[PageBacklink]:
    """What links to this page (RADD-713) — read from the index maintained on
    save, not by scanning every body."""
    await _page_guard(session, user, page_id, authz.Permission.PAGE_READ)
    return await backlinks.backlink_reads(session, page_id)


@router.post("/pages/reindex-links")
async def reindex_links(session: Session, user: CurrentUser) -> dict[str, int]:
    """Rebuild the whole backlink index. It is derived data, so running it is
    always safe; it exists for after a bulk import, which writes pages without
    going through the normal save path."""
    await authz.require(session, user, authz.Permission.PAGE_MANAGE)
    return {"pages_indexed": await backlinks.reindex_all(session)}


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
#
# `/pages/search` is declared UP with the other literal `/pages/<word>` routes,
# above `/pages/{page_id}` — see the note there. It used to live here, where
# FastAPI's first-match-wins ordering made it unreachable (RADD-761).
