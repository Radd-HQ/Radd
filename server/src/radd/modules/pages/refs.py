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

Also here: the two READ seams `notify` calls back into. They live beside the
refs because they answer the same question from the other end — the refs say
what a page IS, these say who may hear about it.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from .models import Page, PageSpace

if TYPE_CHECKING:  # deferred: auth loads before pages
    from radd.modules.auth.models import User


async def page_ref(session: AsyncSession, page_id) -> dict | None:
    """`{id, number, title, slug, version}` — what an inbox row renders and links without a join."""
    page = await session.get(Page, page_id)
    if page is None:
        return None
    return {
        "id": str(page.id),
        "number": page.number,
        "title": page.title,
        "slug": page.slug,
        "version": page.version,
    }


async def space_ref(session: AsyncSession, space_id) -> dict | None:
    """`{id, name, slug}` — the id a space subscription matches on, plus the slug
    the notification's link needs."""
    space = await session.get(PageSpace, space_id)
    if space is None:
        return None
    return {"id": str(space.id), "name": space.name, "slug": space.slug}


async def space_of_page_ref(session: AsyncSession, page_id: uuid.UUID) -> dict | None:
    """The SPACE ref for a page, by page id.

    `comment.created` names the page as its parent and nothing else — `comments`
    is polymorphic and resolves an `item` subject only for item parents — so a
    consumer fanning out a page comment has an id and no space, and a space is
    what a wiki subscription is scoped to.
    """
    page = await session.get(Page, page_id)
    if page is None:
        return None
    return await space_ref(session, page.space_id)


async def page_watcher_ids(session: AsyncSession, page_id: uuid.UUID) -> list[uuid.UUID]:
    """Who follows this page. Re-exported here so `notify` has ONE door into
    this module rather than importing whichever file happens to hold the table."""
    from . import watchers

    return await watchers.watcher_ids(session, page_id)


async def readable_page_ids_for_users(
    session: AsyncSession, page_id: uuid.UUID, user_ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    """Which of these people may READ this page (spec 118's delivery gate).

    The wiki's answer to `notify.consumer._allowed`, and it has to be the wiki's
    answer: a page's visibility is a space role PLUS every restriction on the
    ancestor path (RADD-948), which is three layers `notify` would have to
    reimplement and then keep in step. Batched per page rather than per person
    because one edit notifies a handful of watchers and the space permission
    lookup is the expensive part.

    A missing page reads as "nobody" — a notification about a page that has been
    deleted between the edit and the fan-out has nothing to link to anyway.
    """
    if not user_ids:
        return set()
    from radd.modules.auth import service as auth

    from . import page_access

    page = await session.get(Page, page_id)
    if page is None:
        return set()
    users = await auth.users_by_ids(session, set(user_ids))
    allowed: set[uuid.UUID] = set()
    for user_id in user_ids:
        user: "User | None" = users.get(user_id)
        if user is None or not user.active:
            continue
        if await page_access.page_access(session, user, page):
            allowed.add(user_id)
    return allowed
