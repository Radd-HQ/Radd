"""Pure decision helpers for the pages module (unit-tested, no DB): tree cycles,
version snapshots, slugs, paths, archived-subtree visibility."""

import uuid
from collections.abc import Collection, Iterable, Mapping, Sequence
from typing import Protocol

from .types import SLUG_MAX_CHARS, SLUG_SEPARATOR_RE


def would_create_cycle(
    page_id: uuid.UUID,
    new_parent_id: uuid.UUID | None,
    parent_of: Mapping[uuid.UUID, uuid.UUID | None],
) -> bool:
    """True if re-parenting `page_id` under `new_parent_id` closes a loop.

    `parent_of` maps every page in the space to its CURRENT parent (None =
    root). Walk the ancestor chain from the new parent up: hitting `page_id`
    (including new_parent_id == page_id itself) means the move would make the
    page its own ancestor. A walk longer than the map is a pre-existing loop —
    treat it as a cycle rather than spinning.
    """
    current = new_parent_id
    for _ in range(len(parent_of) + 1):
        if current is None:
            return False
        if current == page_id:
            return True
        current = parent_of.get(current)
    return True


def should_snapshot(
    current_title: str, current_body: str, new_title: str | None, new_body: str | None
) -> bool:
    """Whether a PATCH is content-changing: snapshot the previous content and
    bump `version`. None = field omitted; equal values are no-ops (a pure move
    or a same-text save must NOT burn a version).
    """
    title_changed = new_title is not None and new_title != current_title
    body_changed = new_body is not None and new_body != current_body
    return title_changed or body_changed


def slugify(name: str) -> str:
    """Space name → its slug: lowercase, dash-separated, bounded."""
    slug = SLUG_SEPARATOR_RE.sub("-", name.lower()).strip("-")
    return slug[:SLUG_MAX_CHARS] or "space"


#: A page slug may be longer than a space slug — page titles are sentences.
PAGE_SLUG_MAX_CHARS = 120


def page_slugify(title: str) -> str:
    """Page title → the URL segment (RADD-702). `page` is the fallback for a
    title that is entirely punctuation or non-Latin: a URL still has to exist,
    and the per-space uniqueness pass will make it `page-2`, `page-3`, …"""
    slug = SLUG_SEPARATOR_RE.sub("-", title.lower()).strip("-")
    return slug[:PAGE_SLUG_MAX_CHARS] or "page"


def unique_slug(candidate: str, taken: Collection[str]) -> str:
    """`candidate`, or the first free `candidate-2`, `candidate-3`, … — the one
    collision rule, shared by creation and rename."""
    if candidate not in taken:
        return candidate
    suffix = 2
    while f"{candidate}-{suffix}" in taken:
        suffix += 1
    return f"{candidate}-{suffix}"


class PathRow(Protocol):
    """What the path helpers need of a page row — the tree's three columns."""

    id: uuid.UUID
    parent_id: uuid.UUID | None
    slug: str


def page_paths(rows: Iterable[PathRow]) -> dict[uuid.UUID, str]:
    """Every row's space-relative path, `parent-slug/child-slug/…`, folded over
    the rows (RADD-1233). A row whose parent is missing (a restricted ancestor
    the reader filter dropped) starts where its visible ancestry does."""
    by_id = {row.id: row for row in rows}
    cache: dict[uuid.UUID, str] = {}

    def path_of(row: PathRow) -> str:
        hit = cache.get(row.id)
        if hit is not None:
            return hit
        segments: list[str] = []
        current: PathRow | None = row
        for _ in range(len(by_id) + 1):
            if current is None:
                break
            segments.append(current.slug)
            current = by_id.get(current.parent_id) if current.parent_id else None
        else:  # a loop in the data: a path that never terminates is no address
            segments = [row.slug]
        result = "/".join(reversed(segments))
        cache[row.id] = result
        return result

    return {row.id: path_of(row) for row in by_id.values()}


def walk_path(rows: Iterable[PathRow], segments: Sequence[str]) -> uuid.UUID | None:
    """The page at `segments`, walking from the root, or None. `rows` need hold
    only the candidates (slug in `segments`): the walk matches `parent_id` level
    by level, so a same-named page at another depth never matches."""
    if not segments:
        return None
    by_parent: dict[uuid.UUID | None, dict[str, uuid.UUID]] = {}
    for row in rows:
        by_parent.setdefault(row.parent_id, {})[row.slug] = row.id
    parent: uuid.UUID | None = None
    for segment in segments:
        found = by_parent.get(parent, {}).get(segment)
        if found is None:
            return None
        parent = found
    return parent


def ancestor_ids(
    parent_of: Mapping[uuid.UUID, uuid.UUID | None], page_id: uuid.UUID
) -> list[uuid.UUID]:
    """`page_id`'s ancestors, nearest first, stopping at a root or at a parent
    outside `parent_of`. Bounded by the map's size, so a loop in the data ends
    instead of spinning."""
    chain: list[uuid.UUID] = []
    current = parent_of.get(page_id)
    for _ in range(len(parent_of) + 1):
        if current is None or current not in parent_of:
            break
        chain.append(current)
        current = parent_of[current]
    return chain


def visible_page_ids(
    parent_of: Mapping[uuid.UUID, uuid.UUID | None],
    archived: frozenset[uuid.UUID] | set[uuid.UUID],
) -> set[uuid.UUID]:
    """Pages visible in the tree: not archived and no archived ancestor —
    archiving prunes a subtree without touching its rows."""
    visible: set[uuid.UUID] = set()
    for page_id in parent_of:
        current: uuid.UUID | None = page_id
        hidden = False
        for _ in range(len(parent_of) + 1):
            if current is None:
                break
            if current in archived:
                hidden = True
                break
            current = parent_of.get(current)
        else:  # unterminated chain (data loop) — hide rather than spin
            hidden = True
        if not hidden:
            visible.add(page_id)
    return visible
