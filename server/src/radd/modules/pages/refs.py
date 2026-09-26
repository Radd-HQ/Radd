"""Canonical event-payload refs for a page and a space (RADD-923; spec 118).

Page events used to carry `{"title", "version", "changed"}` and, on create, a
bare `space_id` string. That is enough for a webhook and not nearly enough for a
consumer: `notify` needs the SPACE (a space subscription is scoped to its id)
and the slugs (a notification links `/pages/<space>/<page>` with no join), and
it may not reach into `pages.models` to get them — the spine rule forbids it and
the load order forbids importing pages at all.

So the kernel writes them. The emitters pass ids through `emit(subjects=…)`,
these two functions describe the shapes, and the `EventTypeSpec.subjects`
declaration makes the promise something the loader refuses to boot without.

Who may HEAR about a page is not here any more: notify asks the wiki's
`NOTIFICATION_SUBJECT` provider (`notifications.py`, RADD-1385) on the kernel
socket instead of importing read seams from this file.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from .models import Page, PageSpace


async def page_ref(session: AsyncSession, page_id) -> dict | None:
    """`{id, number, title, slug, version, path, space}` — what an inbox row
    renders and links without a join. RADD-1248 added `path` (the readable
    address's page part) and the SPACE ref, so an automation condition can say
    "in space runbooks" and a template can name the page, from the ref alone."""
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
