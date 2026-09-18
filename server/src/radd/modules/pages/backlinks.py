"""Page → page references, indexed on save (RADD-713).

A wiki without backlinks is a set of dead ends: a page can say what it points at
but never what points at it, which is the direction people actually navigate.

**An index, not a live search.** The obvious alternative — scan every body for a
mention of this page when the page is opened — is `LIKE '%…%'` over the whole
corpus per page view, cannot use the FTS index, and gets slower as the wiki gets
more useful. The write path already parses the body, so maintaining a small
table there costs one extra statement per save and makes the read a single
indexed lookup.

**What counts as a link.** Whatever the editor actually emits for an internal
page reference:

  - `/pages/<space-slug>/<path…>` — the canonical form (RADD-702, RADD-1233:
    the path has as many segments as the page is deep),
  - the same path with the instance's origin in front, because pasting a URL
    from the address bar is how most links get made,
  - `/pages?pageId=<number|uuid>` — the permalink (RADD-1233),
  - `/pages/<uuid>` and bare page UUIDs in a link target, which is what pre-702
    links look like and what the API still accepts.

Resolution runs the same resolver the address bar does (`paths.resolve`), so a
link counts as a backlink exactly when clicking it would land. A link that
resolves to nothing is simply not indexed: pages are written before they exist,
and a dangling link is a normal state of a wiki, not an error to report.
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Page, PageLink, PageSpace
from .schemas import PageBacklink

#: `](/pages/foo/bar)` and `](https://host/pages/foo/bar)`, plus the id forms.
#: Deliberately matches the LINK TARGET rather than any occurrence of the text:
#: a page that merely quotes another page's path in a code sample is not
#: linking to it, and counting it would make backlinks noise.
_LINK_TARGET = re.compile(
    r"]\(\s*(?P<url>[^)\s]+)",  # markdown link target
)
_HTML_HREF = re.compile(r"""href\s*=\s*["'](?P<url>[^"']+)""")

_PAGES_PATH = re.compile(
    r"(?:^|//[^/]+)?/pages/(?P<first>[^/?#\s]+)(?:/(?P<rest>[^?#\s]+))?"
)
_PERMALINK = re.compile(r"(?:^|//[^/]+)?/pages\?(?:[^#\s]*&)?pageId=(?P<key>[^&#\s]+)")


def _targets(body: str) -> tuple[set[tuple[str, str]], set[str]]:
    """(space-slug, path) pairs and page KEYS (a uuid or a number, as text)
    referenced by `body`."""
    paths_: set[tuple[str, str]] = set()
    keys: set[str] = set()
    urls = [match.group("url") for match in _LINK_TARGET.finditer(body)]
    urls += [match.group("url") for match in _HTML_HREF.finditer(body)]
    for url in urls:
        permalink = _PERMALINK.search(url)
        if permalink:
            keys.add(permalink.group("key"))
            continue
        found = _PAGES_PATH.search(url)
        if not found:
            continue
        first, rest = found.group("first"), found.group("rest")
        if rest:
            paths_.add((first, rest))
            continue
        # `/pages/<uuid>` — the pre-702 shape.
        try:
            keys.add(str(uuid.UUID(first)))
        except ValueError:
            continue
    return paths_, keys


async def resolve_targets(session: AsyncSession, body: str) -> set[uuid.UUID]:
    """The page ids `body` links to. Unresolvable links are dropped, not raised:
    linking to a page you are about to write is ordinary wiki behaviour."""
    from radd.exceptions import NotFoundError

    from . import paths
    from .spaces import by_slug_or_id

    page_paths, keys = _targets(body)
    resolved: set[uuid.UUID] = set()
    for key in keys:
        page = await paths.by_key(session, key)
        if page is not None:
            resolved.add(page.id)
    for space_slug, path in page_paths:
        try:
            space = await by_slug_or_id(session, space_slug)
            resolved.add((await paths.resolve(session, space, path)).id)
        except NotFoundError:
            continue
    return resolved


async def reindex(session: AsyncSession, page: Page) -> None:
    """Replace this page's outgoing links. Called from the page write path.

    Replace rather than diff: a body edit can add and remove links in one go, the
    set is small, and a wrong diff leaves a phantom backlink that nobody can
    explain by looking at either page.
    """
    targets = await resolve_targets(session, page.body)
    targets.discard(page.id)  # a page linking to itself is not a backlink
    await session.execute(delete(PageLink).where(PageLink.source_page_id == page.id))
    for target in targets:
        session.add(PageLink(source_page_id=page.id, target_page_id=target))
    await session.flush()


async def backlink_reads(session: AsyncSession, page_id: uuid.UUID, *, actor=None) -> list[PageBacklink]:
    """Live (non-archived) pages linking here, newest edit first.

    Joined to the space because a backlink can come from a different one, and a
    link needs both URL segments — resolving that per row in the client would be
    a fetch per backlink.
    """
    rows = await session.execute(
        select(Page, PageSpace.slug)
        .join(PageLink, PageLink.source_page_id == Page.id)
        .join(PageSpace, PageSpace.id == Page.space_id)
        .where(PageLink.target_page_id == page_id, Page.archived_at.is_(None))
        .order_by(Page.updated_at.desc())
    )
    pairs = rows.all()
    if actor is not None:
        from .page_access import readable_page_ids
        allowed = await readable_page_ids(session, actor, [page for page, _ in pairs])
        pairs = [(page, slug) for page, slug in pairs if page.id in allowed]
    from . import paths

    page_paths = await paths.paths_for(session, [page for page, _ in pairs])
    return [
        PageBacklink(
            id=page.id,
            number=page.number,
            title=page.title,
            slug=page.slug,
            path=page_paths[page.id],
            space_id=page.space_id,
            space_slug=space_slug,
            updated_at=page.updated_at,
        )
        for page, space_slug in pairs
    ]


async def reindex_all(session: AsyncSession) -> int:
    """Rebuild the index for every live page. Derived data, so this is always
    safe; it exists for content that arrived without passing the save path (an
    import), where the index would otherwise stay empty."""
    pages = list((await session.execute(select(Page).where(Page.archived_at.is_(None)))).scalars())
    for page in pages:
        await reindex(session, page)
    return len(pages)
