"""Page addresses (RADD-1233): the id is the key, the path is how people say it.

A page has three addresses and one identity:

- `pages.id` — the key everything joins on;
- `pages.number` — the same identity as a small integer, for a permalink
  (`/pages?pageId=12402`) that survives every rename and move;
- `<space>/<slug>/<slug>/…` — the hierarchical, readable address, derived
  from the tree and never stored.

Resolving a path is ONE query: every live page in the space whose slug appears
in the path's segment set, then a walk from the root in memory
(`core.walk_path`). Same-named pages at other depths are in the result set and
simply never match their level's parent. Nothing is denormalised, so a move or
rename rewrites nothing.

When the walk fails, the path is looked up EXACTLY in `page_path_history` —
every address the page and its descendants ever had is written there on
rename, move and restore — so a stale link lands on the page it named, never
on a same-named neighbour. Last, a single segment is tried as a bare slug
anywhere in the space: what a pre-1233 `/pages/<space>/<slug>` link to a
nested page looks like. One match resolves (the client then redirects to the
current path); several is a 404, not a guess.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import NotFoundError

from . import core
from .models import Page, PagePathHistory, PageSpace
from .types import PageEntity

#: What separates a path's segments in a URL and in `PageRead.path`.
SEPARATOR = "/"


def split(path: str) -> list[str]:
    """`a/b//c/` → `["a", "b", "c"]` — empty segments are what a doubled or
    trailing slash leaves behind, never a page."""
    return [segment for segment in path.split(SEPARATOR) if segment]


async def resolve(session: AsyncSession, space: PageSpace, path: str) -> Page:
    """The page at `path` inside `space`, or raise NotFound.

    A single segment that parses as a UUID or an integer is the page's id or
    number (a permalink, or a pre-702 link) — checked before any slug, since a
    slug is never shaped like either.
    """
    segments = split(path)
    if not segments:
        raise NotFoundError(PageEntity.PAGE, f"{space.slug}/")
    if len(segments) == 1:
        by_key = await _by_key(session, segments[0], space.id)
        if by_key is not None:
            return by_key
    candidates = (
        await session.execute(
            select(Page).where(Page.space_id == space.id, Page.slug.in_(set(segments)))
        )
    ).scalars().all()
    # Live pages first: a live page and an archived one may share a path (the
    # archived one no longer holds the name), and the address means the live
    # page. An archived page with no live namesake is still reachable by its
    # path — the archive browser links it that way.
    found = core.walk_path([row for row in candidates if row.archived_at is None], segments)
    if found is None:
        found = core.walk_path(candidates, segments)
    if found is not None:
        return next(row for row in candidates if row.id == found)
    stale = await _by_history(session, space.id, join(segments))
    if stale is None and len(segments) == 1:
        stale = await _by_bare_slug(session, space.id, segments[0])
    if stale is None:
        raise NotFoundError(PageEntity.PAGE, f"{space.slug}/{path}")
    return stale


async def by_key(session: AsyncSession, key: str) -> Page | None:
    """A page by its UUID or its number, from ANY space — the permalink lookup."""
    return await _by_key(session, key, None)


async def _by_key(session: AsyncSession, key: str, space_id: uuid.UUID | None) -> Page | None:
    condition = None
    if key.isdigit():
        condition = Page.number == int(key)
    else:
        try:
            condition = Page.id == uuid.UUID(key)
        except ValueError:
            return None
    query = select(Page).where(condition)
    if space_id is not None:
        query = query.where(Page.space_id == space_id)
    return (await session.execute(query)).scalar_one_or_none()


async def _by_history(session: AsyncSession, space_id: uuid.UUID, path: str) -> Page | None:
    """The page that most recently answered to `path` in this space, if any."""
    return (
        await session.execute(
            select(Page)
            .join(PagePathHistory, PagePathHistory.page_id == Page.id)
            .where(PagePathHistory.space_id == space_id, PagePathHistory.path == path)
            .order_by(PagePathHistory.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _by_bare_slug(session: AsyncSession, space_id: uuid.UUID, slug: str) -> Page | None:
    """Exactly one live page in the space with this slug, at any depth, or None."""
    rows = (
        await session.execute(
            select(Page)
            .where(Page.space_id == space_id, Page.archived_at.is_(None), Page.slug == slug)
            .limit(2)
        )
    ).scalars().all()
    return rows[0] if len(rows) == 1 else None


async def paths_for(session: AsyncSession, pages: Iterable[Page]) -> dict[uuid.UUID, str]:
    """Space-relative paths for `pages`, which may span spaces. One query per
    involved space, over rows the tree already loads whole — the same fold
    `core.page_paths` runs for the rail."""
    pages = list(pages)
    if not pages:
        return {}
    space_ids = {page.space_id for page in pages}
    rows = (
        await session.execute(select(Page).where(Page.space_id.in_(space_ids)))
    ).scalars().all()
    all_paths = core.page_paths(rows)
    return {page.id: all_paths.get(page.id, page.slug) for page in pages}


def join(segments: Sequence[str]) -> str:
    return SEPARATOR.join(segments)
