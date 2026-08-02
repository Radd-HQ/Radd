"""Pure decision helpers for the pages module (unit-tested, no DB).

The service layer feeds these plain values so the invariants many flows depend
on — no page-tree cycles, when an edit snapshots a version — stay testable
without a database.
"""

import uuid
from collections.abc import Mapping

from .types import MAX_QUERY_CHARS, SLUG_MAX_CHARS, SLUG_SEPARATOR_RE, TSQUERY_TOKEN_RE


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


def build_tsquery(q: str) -> str:
    """User text → a safe prefix tsquery string: `render & farm:*` (pure).

    Same contract as the search module's: tokenize on non-word separators
    (dropping tsquery metacharacters), AND the terms, prefix-star the LAST
    term so type-ahead matches mid-word. Empty result = nothing searchable.
    """
    tokens = TSQUERY_TOKEN_RE.findall(q[:MAX_QUERY_CHARS])
    if not tokens:
        return ""
    quoted = [f"'{token}'" for token in tokens]
    quoted[-1] += ":*"
    return " & ".join(quoted)


def slugify(name: str) -> str:
    """Space name → a cosmetic slug: lowercase, dash-separated, bounded."""
    slug = SLUG_SEPARATOR_RE.sub("-", name.lower()).strip("-")
    return slug[:SLUG_MAX_CHARS] or "space"


def visible_page_ids(
    parent_of: Mapping[uuid.UUID, uuid.UUID | None],
    archived: frozenset[uuid.UUID] | set[uuid.UUID],
) -> set[uuid.UUID]:
    """Pages visible in the tree: not archived and no archived ancestor.

    Archiving prunes the whole subtree from the default listing without
    touching descendant rows (they come back when the ancestor is restored).
    """
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
