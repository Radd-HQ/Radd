"""Public (no-login) knowledge-base reads — spec 74.

The `public` flag on a PageSpace IS the credential: everything here 404s unless
the page's space is public, and archived pages (or pages under an archived
ancestor) never leak. Bodies only — versions/history/links stay authenticated.

This module is also the seam the forms public deflection imports (deferred,
feature-detected — see forms/public.py), so it exposes plain service functions
rather than router-only logic.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import NotFoundError

from . import search, service
from .models import Page, PageSpace
from .schemas import (
    DocSearchResult,
    PublicPageNode,
    PublicPageRead,
    PublicPageSpace,
)
from .types import PageEntity


async def list_public_spaces(session: AsyncSession) -> list[PublicPageSpace]:
    """Every public space, instance-wide (spec 74: `public` means public)."""
    result = await session.execute(
        select(PageSpace).where(PageSpace.public.is_(True)).order_by(PageSpace.position, PageSpace.name)
    )
    return [PublicPageSpace.model_validate(space) for space in result.scalars()]


async def get_public_space(session: AsyncSession, space_id: uuid.UUID) -> PageSpace:
    """404 for unknown AND non-public alike — existence must not leak."""
    space = await session.get(PageSpace, space_id)
    if space is None or not space.public:
        raise NotFoundError(PageEntity.SPACE, space_id)
    return space


async def public_tree(session: AsyncSession, space_id: uuid.UUID) -> list[PublicPageNode]:
    """The non-archived page tree of a public space (archived subtrees pruned
    by the same visibility rules as the authed listing)."""
    await get_public_space(session, space_id)
    return [
        PublicPageNode(
            id=row.id,
            parent_id=row.parent_id,
            title=row.title,
            slug=row.slug,
            position=row.position,
        )
        for row in await service.list_pages(session, space_id)
    ]


async def public_page(session: AsyncSession, page_id: uuid.UUID) -> PublicPageRead:
    """One page's body + breadcrumb — 404 unless its space is public and the
    page is visible (not archived, no archived ancestor). Every failure mode is
    the SAME page-404 so nothing about internal content leaks."""
    page = await session.get(Page, page_id)
    if page is None:
        raise NotFoundError(PageEntity.PAGE, page_id)
    space = await session.get(PageSpace, page.space_id)
    if space is None or not space.public:
        raise NotFoundError(PageEntity.PAGE, page_id)
    visible = {row.id for row in await service.list_pages(session, page.space_id)}
    if page.id not in visible:
        raise NotFoundError(PageEntity.PAGE, page_id)
    read = await service.page_read(session, page)
    return PublicPageRead(
        id=read.id,
        space_id=read.space_id,
        title=read.title,
        body=read.body,
        breadcrumb=read.breadcrumb,
        updated_at=read.updated_at,
    )


async def search_public(
    session: AsyncSession,
    q: str,
    *,
    space_id: uuid.UUID | None = None,
    limit: int = 20,
) -> list[DocSearchResult]:
    """Live FTS over PUBLIC spaces only (the shared tsvector expression in
    search.search_pages, instance-wide). An optional `space_id` pins one space —
    404 first when that space isn't public, so the filter can't probe."""
    if space_id is not None:
        await get_public_space(session, space_id)
    return await search.search_pages(
        session, q, limit=limit, public_only=True, space_id=space_id
    )