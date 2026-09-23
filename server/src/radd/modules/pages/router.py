import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from radd.choices import ChoiceRead
from radd.db import get_session
from radd.kernel.registry import registries
from radd.modules.auth import authz
from radd.modules.auth.deps import Actor, CurrentUser
from radd.modules.items import service as items_service

from . import (
    paths,
    access,
    directory,
    options as space_options,
    page_access,
    backlinks,
    export as page_export,
    labels as page_labels,
    links,
    mentions as page_mentions,
    search,
    service,
    spaces,
    templates as page_templates,
    template_directory,
    watchers as page_watchers,
)
from radd import tasklists
from radd.exceptions import ConflictError, NotFoundError
from radd.tasklists import TaskToggle

from .models import PageTemplate
from radd.modules.events import service as events

from .types import PageEntity, PageEvent
from .schemas import (
    DocLinkCreate,
    PageLinkedItem,
    PageBacklink,
    PageCreate,
    PageLabelled,
    PageLabelsUpdate,
    PageTemplateCreate,
    PageTemplateRead,
    PageTemplateSummaryRead,
    PageTemplateUpdate,
    PageExtensionRead,
    PageRead,
    PageSummary,
    PageUpdate,
    DocRestoreRequest,
    PageSearchResponse,
    PageSpaceCreate,
    PageSpaceRead,
    PageSpaceSummaryRead,
    PageSpaceUpdate,
    PageVersionMeta,
    PageVersionRead,
    ItemPageRef,
    SpacePublicAccessUpdate,
    PageBulkRequest,
    PageBulkResult,
    PageBulkSkip,
)

router = APIRouter(tags=["pages"])

Session = Annotated[AsyncSession, Depends(get_session)]


# --- spaces ---


@router.get("/page-spaces", response_model=list[PageSpaceRead])
async def list_spaces(
    session: Session, user: Actor, response: Response,
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[PageSpaceRead]:
    """Readable spaces, with optional bounded search windows for interactive readers."""
    rows, total = await directory.page(session, user, q=q, limit=limit, offset=offset)
    response.headers["X-Total-Count"] = str(total)
    return rows


@router.get("/page-spaces/summary", response_model=PageSpaceSummaryRead)
async def space_summary(session: Session, user: Actor) -> PageSpaceSummaryRead:
    return await directory.summary(session, user)


@router.get("/page-spaces/by-identity/{identifier}", response_model=PageSpaceRead)
async def space_by_identity(identifier: str, session: Session, user: Actor) -> PageSpaceRead:
    return await directory.by_identity(session, user, identifier)


@router.get("/page-spaces/options", response_model=list[ChoiceRead])
async def space_choices(
    session: Session, user: CurrentUser, response: Response,
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    value: Annotated[str | None, Query(max_length=200)] = None,
) -> list[ChoiceRead]:
    rows, total = await space_options.list_options(
        session, user, q=q, limit=limit, offset=offset, value=value
    )
    response.headers["X-Total-Count"] = str(total)
    return rows


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


@router.put("/page-spaces/{space_id}/public-access", response_model=PageSpaceRead)
async def set_space_public_access(
    space_id: uuid.UUID, data: SpacePublicAccessUpdate, session: Session, user: CurrentUser
) -> PageSpaceRead:
    """Spec 121 §5 (RADD-1147): a public space IS the Public role granted to
    Anyone on it — written here as that grant, read back as `public`."""
    from radd.modules.auth import public_access  # deferred: auth loads after pages' models

    space = await spaces.get_space(session, space_id)
    await authz.require(session, user, authz.Permission.PAGE_MANAGE, space_id=space.id)
    changed = await public_access.set_space_public(
        session, space.id, public=data.public, actor_id=user.id
    )
    if changed:  # spec 123: the switch is its own audit row, old → new
        await events.emit(
            session,
            event_type=PageEvent.SPACE_PUBLIC_ACCESS_CHANGED,
            entity_type=PageEntity.SPACE,
            entity_id=space.id,
            actor_id=user.id,
            subjects={"page_space": space.id},
            changes=[{"field": "public", "from": not data.public, "to": data.public}],
        )
    return (await spaces.read_spaces(session, [space]))[0]


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
    user: Actor,
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


@router.post("/page-spaces/{space_id}/archived/restore", response_model=PageBulkResult)
async def bulk_restore_archived(
    space_id: uuid.UUID, data: PageBulkRequest, session: Session, user: CurrentUser
) -> PageBulkResult:
    """RADD-1249: restore a selection of archived pages. Per-page gate
    (`page.manage`, the single restore's atom); a refused page is skipped with
    its reason, never a whole-request 403."""
    await spaces.get_space(session, space_id)

    async def guard(page_id: uuid.UUID):
        return await page_access.guard_page(session, user, page_id, authz.Permission.PAGE_MANAGE)

    done, skipped = await service.bulk_restore_pages(session, space_id, data.page_ids, user, guard)
    return PageBulkResult(done=done, skipped=[PageBulkSkip(id=i, reason=r) for i, r in skipped])


@router.post("/page-spaces/{space_id}/archived/delete", response_model=PageBulkResult)
async def bulk_delete_archived(
    space_id: uuid.UUID, data: PageBulkRequest, session: Session, user: CurrentUser
) -> PageBulkResult:
    """RADD-1249: delete a selection of archived pages permanently — the
    single delete's atom (`page.delete`, implied by manage) per page."""
    await spaces.get_space(session, space_id)

    async def guard(page_id: uuid.UUID):
        return await page_access.guard_page(session, user, page_id, authz.Permission.PAGE_DELETE)

    done, skipped = await service.bulk_delete_pages(session, space_id, data.page_ids, user, guard)
    return PageBulkResult(done=done, skipped=[PageBulkSkip(id=i, reason=r) for i, r in skipped])


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
    readable = None
    if space_id is not None:
        await authz.require(session, user, authz.Permission.PAGE_READ, space_id=space_id)
    else:
        readable = await access.readable_spaces(session, user)
        if not readable:
            return []
    return [
        PageTemplateRead.model_validate(t)
        for t in await page_templates.list_templates(session, space_id, readable_space_ids=readable)
    ]


@router.get("/page-templates/directory", response_model=list[PageTemplateSummaryRead])
async def template_page(
    session: Session, user: CurrentUser, response: Response,
    q: Annotated[str, Query(max_length=200)] = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[PageTemplateSummaryRead]:
    rows, total = await template_directory.page(session, user, q=q, limit=limit, offset=offset)
    response.headers["X-Total-Count"] = str(total)
    return rows


@router.get("/page-templates/{template_id}", response_model=PageTemplateRead)
async def template_detail(template_id: uuid.UUID, session: Session, user: CurrentUser) -> PageTemplateRead:
    return await template_directory.by_id(session, user, template_id)


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
async def list_page_extensions(session: Session, user: Actor) -> list[PageExtensionRead]:
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


@router.post("/pages/reindex")
async def reindex_pages(session: Session, user: CurrentUser) -> dict[str, int]:
    """Rebuild both derived indexes over every live page (RADD-943).

    Page→page backlinks and page→issue links are maintained on save, so they
    only exist for content that passed the save path — a page written before
    either shipped, or created by an importer, carries neither. This is the one
    call that fixes that, and it is idempotent: both indexes are derived from
    the body, so running it twice changes nothing.

    Registered BEFORE `/pages/{page_id}`, or the literal segment would be parsed
    as a UUID and never reached (RADD-761).
    """
    await authz.require(session, user, authz.Permission.PAGE_MANAGE)
    return {
        "backlinks": await backlinks.reindex_all(session),
        "item_links": await page_mentions.reindex_all(session),
    }


@router.get("/pages/by-path/{space_slug}/{path:path}", response_model=PageRead)
async def get_page_by_path(
    space_slug: str, path: str, session: Session, user: Actor
) -> PageRead:
    """`/pages/<space>/<slug>/<slug>/…` (RADD-702, RADD-1233). Registered BEFORE
    `/pages/{page_id}` so `by-path` is never parsed as a UUID. The space segment
    may be an id; a single page segment may be an id or a number, which is what
    lets every pre-1233 link resolve and redirect instead of rotting. The
    answer carries the CANONICAL `path`; a client that arrived by any other
    address compares and redirects."""
    space = await spaces.by_slug_or_id(session, space_slug)
    # Check the space BEFORE resolving inside it — a path is not a permission —
    # then the page's own restriction (RADD-792): a restricted page 404s rather
    # than 403ing, so its EXISTENCE stays private.
    await authz.require(session, user, authz.Permission.PAGE_READ, space_id=space.id)
    page = await paths.resolve(session, space, path)
    if not await page_access.page_access(session, user, page):
        raise NotFoundError(PageEntity.PAGE, page.id)
    return await service.page_read(session, page)


@router.get("/pages/by-number/{number}", response_model=PageRead)
async def get_page_by_number(number: int, session: Session, user: Actor) -> PageRead:
    """The permalink lookup (RADD-1233): `/pages?pageId=12402` → this. Also
    before `/pages/{page_id}`, for the same reason as `by-path`."""
    page = await paths.by_key(session, str(number))
    if page is None:
        raise NotFoundError(PageEntity.PAGE, str(number))
    await authz.require(session, user, authz.Permission.PAGE_READ, space_id=page.space_id)
    if not await page_access.page_access(session, user, page):
        raise NotFoundError(PageEntity.PAGE, page.id)
    return await service.page_read(session, page)


@router.get("/pages/search", response_model=PageSearchResponse)
async def search_docs(
    q: str, session: Session, user: Actor, limit: int = 20
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
async def get_page(page_id: uuid.UUID, session: Session, user: Actor) -> PageRead:
    page = await page_access.guard_page(session, user, page_id, authz.Permission.PAGE_READ)
    return await service.page_read(session, page)


@router.patch("/pages/{page_id}", response_model=PageRead)
async def update_page(
    page_id: uuid.UUID, data: PageUpdate, session: Session, user: CurrentUser
) -> PageRead:
    await page_access.guard_page(session, user, page_id, authz.Permission.PAGE_WRITE)
    page = await service.update_page(session, page_id, data, user.id)
    return await service.page_read(session, page)


@router.post("/pages/{page_id}/tasks", response_model=PageRead)
async def toggle_page_task(
    page_id: uuid.UUID, data: TaskToggle, session: Session, user: CurrentUser
) -> PageRead:
    """Tick or untick one checklist box without opening the editor (RADD-1296).
    An ordinary versioned save: page.write, `expected_version`, a history row,
    and the spec-122 guard refuses it while someone is editing the page live."""
    page = await page_access.guard_page(session, user, page_id, authz.Permission.PAGE_WRITE)
    try:
        body = tasklists.toggle(page.body or "", data)
    except tasklists.TaskToggleConflict as exc:
        raise ConflictError(PageEntity.PAGE, reason=str(exc)) from exc
    page = await service.update_page(
        session, page_id, PageUpdate(body=body, expected_version=page.version), user.id
    )
    return await service.page_read(session, page)


@router.delete("/pages/{page_id}", status_code=204)
async def delete_page(
    page_id: uuid.UUID, session: Session, user: CurrentUser, hard: bool = False
) -> None:
    # spec 50: hard-delete is its own atom (page.delete, implied by page.manage).
    permission = authz.Permission.PAGE_DELETE if hard else authz.Permission.PAGE_WRITE
    await page_access.guard_page(session, user, page_id, permission)
    if hard:
        await service.hard_delete_page(session, page_id, user.id)
    else:
        await service.archive_page(session, page_id, user.id)


@router.post("/pages/{page_id}/unarchive", response_model=PageRead)
async def unarchive_page(
    page_id: uuid.UUID, session: Session, user: CurrentUser
) -> PageRead:
    await page_access.guard_page(session, user, page_id, authz.Permission.PAGE_MANAGE)
    page = await service.unarchive_page(session, page_id, user.id)
    return await service.page_read(session, page)


# --- versions ---


@router.get("/pages/{page_id}/export")
async def export_page(page_id: uuid.UUID, session: Session, user: CurrentUser) -> Response:
    """One page and everything beneath it, as a zip of markdown."""
    page = await page_access.guard_page(session, user, page_id, authz.Permission.PAGE_READ)
    space = await spaces.get_space(session, page.space_id)
    name, blob = await page_export.export_zip(session, space, root=page, actor=user)
    return _zip_response(name, blob)


def _zip_response(name: str, blob: bytes) -> Response:
    return Response(
        content=blob,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/pages/by-label/{name}", response_model=list[PageLabelled])
async def pages_by_label(
    name: str, session: Session, user: Actor, space: str = ""
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
    await page_access.guard_page(session, user, page_id, authz.Permission.PAGE_WRITE)
    labels = await page_labels.set_labels(session, page_id, data.labels, user.id)
    return [label.name for label in labels]


@router.get("/pages/{page_id}/watch")
async def get_watch(page_id: uuid.UUID, session: Session, user: CurrentUser) -> dict[str, bool]:
    await page_access.guard_page(session, user, page_id, authz.Permission.PAGE_READ)
    return {"watching": await page_watchers.is_watching(session, page_id, user.id)}


@router.put("/pages/{page_id}/watch")
async def set_watch(page_id: uuid.UUID, session: Session, user: CurrentUser) -> dict[str, bool]:
    """Watch a page (RADD-719). Idempotent — watching twice is a double click."""
    await page_access.guard_page(session, user, page_id, authz.Permission.PAGE_READ)
    await page_watchers.watch(session, page_id, user.id)
    return {"watching": True}


@router.delete("/pages/{page_id}/watch")
async def clear_watch(page_id: uuid.UUID, session: Session, user: CurrentUser) -> dict[str, bool]:
    await page_access.guard_page(session, user, page_id, authz.Permission.PAGE_READ)
    await page_watchers.unwatch(session, page_id, user.id)
    return {"watching": False}


@router.get("/pages/{page_id}/backlinks", response_model=list[PageBacklink])
async def list_backlinks(
    page_id: uuid.UUID, session: Session, user: Actor
) -> list[PageBacklink]:
    """What links to this page (RADD-713) — read from the index maintained on
    save, not by scanning every body."""
    await page_access.guard_page(session, user, page_id, authz.Permission.PAGE_READ)
    return await backlinks.backlink_reads(session, page_id, actor=user)


@router.get("/pages/{page_id}/versions", response_model=list[PageVersionMeta])
async def list_versions(
    page_id: uuid.UUID, session: Session, user: CurrentUser
) -> list[PageVersionMeta]:
    await page_access.guard_page(session, user, page_id, authz.Permission.PAGE_READ)
    return [PageVersionMeta.model_validate(v) for v in await service.list_versions(session, page_id)]


@router.get("/pages/{page_id}/versions/{version}", response_model=PageVersionRead)
async def get_version(
    page_id: uuid.UUID, version: int, session: Session, user: CurrentUser
) -> PageVersionRead:
    await page_access.guard_page(session, user, page_id, authz.Permission.PAGE_READ)
    return PageVersionRead.model_validate(await service.get_version(session, page_id, version))


@router.post("/pages/{page_id}/restore", response_model=PageRead)
async def restore_version(
    page_id: uuid.UUID, data: DocRestoreRequest, session: Session, user: CurrentUser
) -> PageRead:
    await page_access.guard_page(session, user, page_id, authz.Permission.PAGE_WRITE)
    page = await service.restore_version(session, page_id, data.version, user.id)
    return await service.page_read(session, page)


# --- issue links ---


@router.get("/pages/{page_id}/items", response_model=list[PageLinkedItem])
async def linked_items(
    page_id: uuid.UUID, session: Session, user: Actor
) -> list[PageLinkedItem]:
    await page_access.guard_page(session, user, page_id, authz.Permission.PAGE_READ)
    return await links.linked_items(session, page_id, user)


@router.post("/pages/{page_id}/items", response_model=PageLinkedItem, status_code=201)
async def link_item(
    page_id: uuid.UUID, data: DocLinkCreate, session: Session, user: CurrentUser
) -> PageLinkedItem:
    await page_access.guard_page(session, user, page_id, authz.Permission.PAGE_WRITE)
    return await links.link_item(session, page_id, data.item_key, user)


@router.delete("/pages/{page_id}/items/{item_id}", status_code=204)
async def unlink_item(
    page_id: uuid.UUID, item_id: uuid.UUID, session: Session, user: CurrentUser
) -> None:
    await page_access.guard_page(session, user, page_id, authz.Permission.PAGE_WRITE)
    await links.unlink_item(session, page_id, item_id, user.id)


@router.get("/items/{item_id}/pages", response_model=list[ItemPageRef])
async def item_docs(item_id: uuid.UUID, session: Session, user: Actor) -> list[ItemPageRef]:
    """Pages linked to an item — path-extends the items surface (like timelogging)."""
    await items_service.require_readable_item(session, item_id, user)
    return await links.pages_for_item(session, item_id, actor=user)


# --- search ---
#
# `/pages/search` is declared UP with the other literal `/pages/<word>` routes,
# above `/pages/{page_id}` — see the note there. It used to live here, where
# FastAPI's first-match-wins ordering made it unreachable (RADD-761).
