"""Markdown export (RADD-721).

Content could go in but not out, which is the wrong gap for a tool whose pitch
includes not being locked in.

Two decisions worth stating.

**Links are rewritten to relative paths.** An export whose links all point back
at the instance is a folder of dead ends the moment you are offline or the
instance is gone — which is exactly the situation an export is FOR. Every
`/pages/<space>/<slug>` that resolves to a page inside the same archive becomes a
relative `.md` path; one that points outside it is left absolute, because a link
to a page you did not export is genuinely a link to the instance.

**Extension fences are written out verbatim.** They are markdown to every other
reader (RADD-709), they degrade to a labelled code block anywhere else, and
leaving them intact is what lets an export be re-imported without losing them.
Rendering them to static text here would be a one-way door.
"""

from __future__ import annotations

import io
import re
import uuid
import zipfile

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import core
from .core import page_slugify
from .models import Page, PageSpace

#: Windows forbids these outright; the rest of the world merely regrets them.
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

_PAGE_LINK = re.compile(
    r"(?P<open>]\(\s*|href\s*=\s*[\"'])"
    r"(?:https?://[^/\s)\"']+)?/pages/(?P<space>[^/?#\s)\"']+)/(?P<page>[^?#\s)\"']+)"
)


def safe_name(title: str, fallback: str) -> str:
    """A file name from a page title. Slug rather than the raw title: a wiki is
    full of titles containing slashes and colons, and the point of an export is
    that it survives being copied onto another filesystem."""
    cleaned = _UNSAFE.sub("-", title).strip().strip(".")
    # `page_slugify` supplies its OWN fallback for an unsluggable title, which
    # would give every such page the same name and collide them in the archive.
    # Decide emptiness before handing it over.
    if not any(character.isalnum() for character in cleaned):
        return fallback[:80]
    return (page_slugify(cleaned) or fallback)[:80]


def _relative(from_parts: list[str], to_parts: list[str]) -> str:
    """A relative path from one archive entry's DIRECTORY to another entry."""
    from_dir = from_parts[:-1]
    common = 0
    while common < min(len(from_dir), len(to_parts) - 1) and from_dir[common] == to_parts[common]:
        common += 1
    ups = [".."] * (len(from_dir) - common)
    return "/".join([*ups, *to_parts[common:]]) or to_parts[-1]


def rewrite_links(body: str, own_path: list[str], by_slug: dict[tuple[str, str], list[str]]) -> str:
    """Point internal links at their file in the archive; leave the rest alone.
    `by_slug` is keyed by (space slug, page PATH) — RADD-1233."""

    def swap(match: re.Match[str]) -> str:
        target = by_slug.get((match.group("space"), match.group("page").strip("/")))
        if target is None:
            return match.group(0)  # outside the archive — an instance link, honestly
        return match.group("open") + _relative(own_path, target)

    return _PAGE_LINK.sub(swap, body)


async def _tree(session: AsyncSession, space_id: uuid.UUID) -> list[Page]:
    rows = await session.execute(
        select(Page)
        .where(Page.space_id == space_id, Page.archived_at.is_(None))
        .order_by(Page.position, Page.title)
    )
    return list(rows.scalars())


def _paths(pages: list[Page], root_id: uuid.UUID | None) -> dict[uuid.UUID, list[str]]:
    """Archive path per page, mirroring the tree: a page with children becomes a
    directory plus an `index.md`, so the shape on disk is the shape in the rail."""
    by_parent: dict[uuid.UUID | None, list[Page]] = {}
    for page in pages:
        by_parent.setdefault(page.parent_id, []).append(page)
    has_children = {page.parent_id for page in pages if page.parent_id}

    out: dict[uuid.UUID, list[str]] = {}

    def walk(parent: uuid.UUID | None, prefix: list[str]) -> None:
        for index, page in enumerate(by_parent.get(parent, [])):
            name = safe_name(page.title, f"page-{index + 1}")
            if page.id in has_children:
                out[page.id] = [*prefix, name, "index.md"]
                walk(page.id, [*prefix, name])
            else:
                out[page.id] = [*prefix, f"{name}.md"]

    walk(root_id, [])
    return out


async def export_zip(
    session: AsyncSession, space: PageSpace, root: Page | None = None, *, actor=None
) -> tuple[str, bytes]:
    """(filename, zip bytes) for a whole space, or one page's subtree."""
    pages = await _tree(session, space.id)
    if root is not None:
        # Restrict to the subtree, root included.
        keep: set[uuid.UUID] = {root.id}
        changed = True
        while changed:
            changed = False
            for page in pages:
                if page.parent_id in keep and page.id not in keep:
                    keep.add(page.id)
                    changed = True
        pages = [page for page in pages if page.id in keep]

    if actor is not None:
        from .page_access import readable_page_ids
        allowed = await readable_page_ids(session, actor, pages)
        pages = [page for page in pages if page.id in allowed]
    paths = _paths(pages, root.parent_id if root is not None else None)
    # RADD-1233: a link names the page's PATH, so key the archive map by it —
    # computed over the whole tree, since a subtree export still links by the
    # page's full address.
    page_paths = core.page_paths(await _tree(session, space.id))
    by_slug = {
        (space.slug, page_paths.get(page.id, page.slug)): paths[page.id]
        for page in pages
        if page.id in paths
    }
    # …and, like the resolver's last-segment fallback, a bare slug that names
    # exactly one exported page: what a pre-1233 link to a nested page is.
    by_last: dict[str, list[list[str]]] = {}
    for page in pages:
        if page.id in paths:
            by_last.setdefault(page.slug, []).append(paths[page.id])
    for slug, targets in by_last.items():
        if len(targets) == 1:
            by_slug.setdefault((space.slug, slug), targets[0])

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for page in pages:
            path = paths.get(page.id)
            if path is None:
                continue
            body = rewrite_links(page.body, path, by_slug)
            # The title is the H1 — a bare body loses it, and the file name is a
            # slug rather than the title it came from.
            archive.writestr("/".join(path), f"# {page.title}\n\n{body}\n")
    stem = safe_name(root.title if root else space.name, "export")
    return f"{stem}.zip", buffer.getvalue()
