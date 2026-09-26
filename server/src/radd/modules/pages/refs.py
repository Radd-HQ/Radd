"""Canonical event-payload refs for a page and a space (RADD-923; spec 118).
The kernel writes them from `emit(subjects=…)`, so consumers such as notify get
the space id and slugs without importing pages."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from .models import Page, PageSpace


async def page_ref(session: AsyncSession, page_id) -> dict | None:
    """`{id, number, title, slug, version, path, space}` — what an inbox row or an
    automation reads without a join (RADD-1248)."""
    page = await session.get(Page, page_id)
    if page is None:
        return None
    segments, cursor, seen = [page.slug], page, {page.id}
    while cursor.parent_id is not None and cursor.parent_id not in seen:
        cursor = await session.get(Page, cursor.parent_id)
        if cursor is None:
            break
        seen.add(cursor.id)
        segments.append(cursor.slug)
    return {
        "id": str(page.id),
        "number": page.number,
        "title": page.title,
        "slug": page.slug,
        "version": page.version,
        "path": "/".join(reversed(segments)),
        "space": await space_ref(session, page.space_id),
    }


async def space_ref(session: AsyncSession, space_id) -> dict | None:
    """`{id, name, slug}` — the id a space subscription matches on, plus the slug
    the notification's link needs."""
    space = await session.get(PageSpace, space_id)
    if space is None:
        return None
    return {"id": str(space.id), "name": space.name, "slug": space.slug}
