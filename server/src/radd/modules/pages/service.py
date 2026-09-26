"""Pages + version history (spec 43). Space CRUD lives in spaces.py.

Optimistic concurrency: a PATCH carrying `expected_version` 409s when stale;
content changes snapshot the PREVIOUS content into page_versions and bump
`version`. Parent moves run the pure cycle guard in core.py.
"""

import re
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, ForbiddenError, NotFoundError, RaddError
from radd.hooks import hooks
from radd.modules.events import service as events
from radd.modules.settings import service as settings_service
from radd.modules.settings.types import SettingKey

from radd.modules.auth import authz
from . import page_access

from . import (
    backlinks,
    core,
    labels as page_labels,
    mentions as page_mentions,
    templates as page_templates,
    watchers as page_watchers,
)
from .core import page_slugify
from .hooks import PageBodyAutosaved, PageBodyWriting, PageHook, PageVersionBumped
from .models import Page, PagePathHistory, PageVersion

if TYPE_CHECKING:  # deferred: auth loads before pages
    from radd.modules.auth.models import User
from .schemas import (
    PageBreadcrumb,
    PageCreate,
    PageRead,
    PageSummary,
    PageUpdate,
    PageSpaceRead,
)
from .spaces import get_space
from .types import PageEntity, PageEvent, RestoreKind
from radd.clock import utcnow


async def _emit_page(
    session: AsyncSession,
    event_type: PageEvent,
    page: Page,
    actor_id: uuid.UUID,
    payload: dict,
    diff: list[dict] | None = None,
) -> None:
    """Every page event names its PAGE and SPACE as subjects; the kernel writes
    both refs (RADD-923). The payload keeps only page-event data."""
    await events.emit(
        session,
        event_type=event_type,
        entity_type=PageEntity.PAGE,
        entity_id=page.id,
        actor_id=actor_id,
        payload=payload,
        subjects={"page": page.id, "page_space": page.space_id},
        changes=diff,
    )


async def get_page(session: AsyncSession, page_id: uuid.UUID) -> Page:
    page = await session.get(Page, page_id)
    if page is None:
        raise NotFoundError(PageEntity.PAGE, page_id)
    return page


async def _space_rows(session: AsyncSession, space_id: uuid.UUID) -> list[Page]:
    result = await session.execute(select(Page).where(Page.space_id == space_id))
    return list(result.scalars())


async def list_pages(
    session: AsyncSession,
    space_id: uuid.UUID,
    *,
    include_archived: bool = False,
    actor: "User | None" = None,
) -> list[PageSummary]:
    """Flat tree rows (the client builds the hierarchy); archived subtrees pruned
    unless `include_archived`. `actor` drops the pages they may not read
    (RADD-792) — every actor-facing caller passes one, since a listed title
    leaks what a restriction hides."""
    rows = await _space_rows(session, space_id)
    if actor is not None:
        readable = await page_access.readable_page_ids(session, actor, list(rows))
        rows = [row for row in rows if row.id in readable]
    parent_of = {row.id: row.parent_id for row in rows}
    if include_archived:
        visible = set(parent_of)
    else:
        archived = {row.id for row in rows if row.archived_at is not None}
        visible = core.visible_page_ids(parent_of, archived)
    children: set[uuid.UUID] = {
        row.parent_id for row in rows if row.parent_id is not None and row.id in visible
    }
    # RADD-718: one labels query for the whole tree, not one per row.
    label_names = await page_labels.labels_for_pages(session, [row.id for row in rows])
    # RADD-1233: paths fold over the rows already in hand — no extra query.
    row_paths = core.page_paths(rows)
    return sorted(
        (
            PageSummary(
                id=row.id,
                number=row.number,
                parent_id=row.parent_id,
                title=row.title,
                slug=row.slug,
                path=row_paths[row.id],
                position=row.position,
                has_children=row.id in children,
                updated_at=row.updated_at,
                labels=label_names.get(row.id, []),
                archived_at=row.archived_at,
            )
            for row in rows
            if row.id in visible
        ),
        key=lambda summary: (summary.position, summary.title),
    )


async def _next_position(
    session: AsyncSession, space_id: uuid.UUID, parent_id: uuid.UUID | None
) -> float:
    highest = await session.scalar(
        select(func.max(Page.position)).where(
            Page.space_id == space_id, Page.parent_id == parent_id
        )
    )
    return (highest or 0) + 1


#: RADD-860: the slugs the create-flow placeholder produces — upgradeable.
_PLACEHOLDER_SLUG_RE = re.compile(r"untitled(-\d+)?")

#: `_reslug`'s "keep the page's current parent" sentinel — None is a real parent.
_SAME_PARENT = object()


async def _free_slug(
    session: AsyncSession,
    space_id: uuid.UUID,
    parent_id: uuid.UUID | None,
    candidate: str,
    *,
    exclude_id: uuid.UUID | None = None,
) -> str:
    """`candidate` made unique among the LIVE SIBLINGS under `parent_id`
    (RADD-1233) — read per call rather than caught as an IntegrityError, since a
    409 is a strange answer to typing a title. Archived siblings do not count."""
    query = select(Page.slug).where(
        Page.space_id == space_id, Page.parent_id == parent_id, Page.archived_at.is_(None)
    )
    if exclude_id is not None:
        query = query.where(Page.id != exclude_id)
    taken = set((await session.execute(query)).scalars())
    return core.unique_slug(page_slugify(candidate), taken)


async def _reslug(
    session: AsyncSession,
    page: Page,
    candidate: str,
    *,
    parent_id: uuid.UUID | None | object = _SAME_PARENT,
) -> bool:
    """Give `page` the slug `candidate`, free among its live siblings — under
    `parent_id` when a move is in flight. True if it changed.

    Runs BEFORE the caller assigns a new parent: the taken-set query autoflushes,
    and a flushed row with the new parent and the old slug is the unique
    violation this avoids."""
    under = page.parent_id if parent_id is _SAME_PARENT else parent_id
    slug = await _free_slug(session, page.space_id, under, candidate, exclude_id=page.id)
    if slug == page.slug:
        return False
    page.slug = slug
    return True


def _remember_paths(
    session: AsyncSession, rows: list[Page], before: dict[uuid.UUID, str]
) -> list[uuid.UUID]:
    """A `page_path_history` row for every page whose path changed since `before`
    (computed over `rows`, which the write mutates in place — so 'after' costs no
    query). A moved ancestor moves its whole subtree's addresses."""
    after = core.page_paths(rows)
    changed: list[uuid.UUID] = []
    for row in rows:
        old = before.get(row.id)
        if old is not None and old != after.get(row.id):
            session.add(PagePathHistory(page_id=row.id, space_id=row.space_id, path=old))
            changed.append(row.id)
    return changed


def _may_import(permissions: "frozenset" = frozenset()) -> bool:
    """Spec 117: import overrides (author, dates, external identity) need
    `page.manage` in the space."""
    return authz.Permission.PAGE_MANAGE in permissions


async def find_by_external(
    session: AsyncSession, external_source: str, external_id: str
) -> Page | None:
    """The page a previous import made from that foreign row (spec 117) — what
    makes re-import an upsert, across runs."""
    if not external_id:
        return None
    return await session.scalar(
        select(Page).where(
            Page.external_source == external_source,
            Page.external_id == external_id,
        )
    )


async def create_page(
    session: AsyncSession,
    data: PageCreate,
    actor_id: uuid.UUID,
    *,
    permissions: "frozenset" = frozenset(),
) -> Page:
    space = await get_space(session, data.space_id)
    if data.parent_id is not None:
        parent = await get_page(session, data.parent_id)
        if parent.space_id != space.id:
            raise ConflictError(PageEntity.PAGE, reason="parent page is in a different space")
        if not _may_import(permissions):
            from radd.modules.auth.service import get_user
            parent_actor = await get_user(session, actor_id)
            await page_access.guard_page(session, parent_actor, parent.id, authz.Permission.PAGE_READ)
            await page_access.guard_page(session, parent_actor, parent.id, authz.Permission.PAGE_WRITE)
    position = (
        data.position
        if data.position is not None
        else await _next_position(session, space.id, data.parent_id)
    )
    body = data.body
    if not body and data.template:
        # RADD-712: an explicit body wins over a named template.
        template = await page_templates.by_name(session, data.template, space_id=space.id)
        author = await _actor_name(session, actor_id)
        body = page_templates.render(template.body, title=data.title, author=author)
    # Spec 117: an import states the author AND the dates — one act, gated together.
    importing = _may_import(permissions)
    author_id = data.author_id if (importing and data.author_id) else actor_id
    page = Page(
        space_id=space.id,
        parent_id=data.parent_id,
        title=data.title,
        slug=await _free_slug(
            session, space.id, data.parent_id, data.slug or page_slugify(data.title)
        ),
        body=body,
        position=position,
        created_by=author_id,
        updated_by=author_id,
        external_source=data.external_source if importing else "",
        external_id=data.external_id if importing else "",
    )
    # Naive UTC, like the columns' server defaults.
    if importing and data.created_at is not None:
        page.created_at = data.created_at.replace(tzinfo=None)
    if importing and (data.updated_at or data.created_at) is not None:
        page.updated_at = (data.updated_at or data.created_at).replace(tzinfo=None)
    session.add(page)
    await session.flush()
    await backlinks.reindex(session, page)  # RADD-713
    await page_mentions.reindex(session, page)  # RADD-943
    await _emit_page(session, PageEvent.PAGE_CREATED, page, actor_id, {"title": page.title})
    return page


async def seal_history(session: AsyncSession, page_id: uuid.UUID) -> Page | None:
    """RADD-1244: close a live session whose last autosaves wrote no history row —
    a row for the CURRENT content, and a bump. Called by the collab room when it
    drops unsealed; a no-op when the page is gone."""
    page = await session.get(Page, page_id)
    if page is None:
        return None
    _snapshot_current(session, page)
    page.version += 1
    await session.flush()
    return page


def _snapshot_current(session: AsyncSession, page: Page) -> None:
    """A history row for the page's CURRENT content, written before it changes."""
    session.add(
        PageVersion(
            page_id=page.id,
            version=page.version,
            title=page.title,
            body=page.body,
            author_id=page.updated_by,
        )
    )


async def _history_window_open(session: AsyncSession, page_id: uuid.UUID) -> bool:
    """Spec 122: whether the page's newest history row is old enough for a
    collaborative autosave to write another. No row yet = open."""
    latest = (
        await session.execute(
            select(func.max(PageVersion.created_at)).where(PageVersion.page_id == page_id)
        )
    ).scalar_one_or_none()
    if latest is None:
        return True
    window = await settings_service.resolve(session, SettingKey.PAGE_COLLAB_VERSION_WINDOW_SECONDS)
    return (utcnow() - latest).total_seconds() >= int(window)


async def _page_diff(
    session: AsyncSession, page: Page, before: dict, changed: list[str]
) -> list[dict]:
    """Spec 123: old → new for title/slug/position, the parent by TITLE, and
    the body only as "changed" (a page body is content, not a value)."""
    diff: list[dict] = []
    for field in ("title", "slug", "position"):
        if field in changed:
            diff.append({"field": field, "from": before[field], "to": getattr(page, field)})
    if "parent_id" in changed:
        titles = {}
        for parent_id in (before["parent_id"], page.parent_id):
            if parent_id is not None:
                parent = await session.get(Page, parent_id)
                titles[parent_id] = parent.title if parent else str(parent_id)
        diff.append(
            {
                "field": "parent",
                "from": titles.get(before["parent_id"]),
                "to": titles.get(page.parent_id),
            }
        )
    if "body" in changed:
        diff.append({"field": "body"})
    return diff


async def update_page(
    session: AsyncSession,
    page_id: uuid.UUID,
    data: PageUpdate,
    actor_id: uuid.UUID,
    *,
    permissions: "frozenset" = frozenset(),
) -> Page:
    page = await get_page(session, page_id)
    before = {
        "title": page.title,
        "slug": page.slug,
        "parent_id": page.parent_id,
        "position": page.position,
    }
    body_changes = data.body is not None and data.body != page.body
    # Spec 122: the live document's holder may refuse a body write not from it, or
    # vouch for one that is. With no subscriber this is a no-op.
    writing = PageBodyWriting(
        page=page,
        actor_id=actor_id,
        collab_session=data.collab_session,
        body_changes=body_changes,
    )
    if data.body is not None or data.collab_session is not None:
        await hooks.dispatch(session, PageHook.BODY_WRITING, writing)
    # A save from the room skips the optimistic check: the room IS the current version.
    if (
        not writing.live_editor
        and data.expected_version is not None
        and data.expected_version != page.version
    ):
        raise ConflictError(
            PageEntity.PAGE,
            reason=f"version conflict: page is at version {page.version}",
        )

    changed: list[str] = []
    moved = False
    # RADD-1233: anything that can change the ADDRESS (a move, a slug, a title
    # upgrading a placeholder slug) snapshots the paths first, for stale links.
    address_may_change = (
        ("parent_id" in data.model_fields_set and data.parent_id != page.parent_id)
        or (data.slug is not None and data.slug != page.slug)
        or (data.title is not None and _PLACEHOLDER_SLUG_RE.fullmatch(page.slug) is not None)
    )
    space_rows = await _space_rows(session, page.space_id) if address_may_change else []
    paths_before = core.page_paths(space_rows) if address_may_change else {}
    if "parent_id" in data.model_fields_set and data.parent_id != page.parent_id:
        if data.parent_id is not None:
            parent = await get_page(session, data.parent_id)
            if parent.space_id != page.space_id:
                raise ConflictError(PageEntity.PAGE, reason="parent page is in a different space")
            if not _may_import(permissions):
                from radd.modules.auth.service import get_user
                parent_actor = await get_user(session, actor_id)
                await page_access.guard_page(session, parent_actor, parent.id, authz.Permission.PAGE_READ)
                await page_access.guard_page(session, parent_actor, parent.id, authz.Permission.PAGE_WRITE)
            parent_of = {row.id: row.parent_id for row in space_rows}
            if core.would_create_cycle(page.id, data.parent_id, parent_of):
                raise ConflictError(PageEntity.PAGE, reason="move would create a cycle")
        # RADD-1233: slugs are unique among SIBLINGS, which a move changes — decided
        # BEFORE the parent moves (see `_reslug`).
        if await _reslug(session, page, page.slug, parent_id=data.parent_id):
            changed.append("slug")
        page.parent_id = data.parent_id
        changed.append("parent_id")
        moved = True
    if data.position is not None and data.position != page.position:
        page.position = data.position
        changed.append("position")
        moved = True
    # RADD-702: the slug changes only when asked — a URL is a promise to whoever
    # has the link. RADD-860: except a PLACEHOLDER (`untitled-N`, which every
    # UI-created page is born with): the first real title upgrades it.
    if data.slug is not None and data.slug != page.slug:
        if await _reslug(session, page, data.slug) and "slug" not in changed:
            changed.append("slug")
    elif (
        data.title is not None
        and data.title != page.title
        and _PLACEHOLDER_SLUG_RE.fullmatch(page.slug)
        and page_slugify(data.title) not in ("untitled", "page")
    ):
        if await _reslug(session, page, data.title) and "slug" not in changed:
            changed.append("slug")
    if address_may_change:
        _remember_paths(session, space_rows, paths_before)

    if core.should_snapshot(page.title, page.body, data.title, data.body):
        importing = _may_import(permissions)
        # Spec 117: an import's construction passes must not consume version numbers.
        quiet_write = importing and data.suppress_version
        # Spec 122: live autosaves coalesce — one history row per window (or on
        # `final`). RADD-1244: `version` moves WITH the row; an autosave inside the
        # window writes only the body, and the room seals the session if it ends
        # without a final save.
        snapshot = not quiet_write and (
            not writing.live_editor
            or data.final
            or await _history_window_open(session, page.id)
        )
        if snapshot:
            _snapshot_current(session, page)
        if data.title is not None and data.title != page.title:
            page.title = data.title
            changed.append("title")
        if data.body is not None and data.body != page.body:
            page.body = data.body
            changed.append("body")
        if snapshot:
            page.version += 1
            await hooks.dispatch(
                session,
                PageHook.VERSION_BUMPED,
                PageVersionBumped(
                    page=page,
                    collab_session=data.collab_session,
                    body_changed="body" in changed,
                    live_editor=writing.live_editor,
                ),
            )
        elif not quiet_write and "body" in changed:
            await hooks.dispatch(session, PageHook.BODY_AUTOSAVED, PageBodyAutosaved(page=page))
        # Spec 117: a re-import credits the revision's real editor.
        page.updated_by = (
            data.author_id if (importing and data.author_id) else actor_id
        )
        if importing and data.updated_at is not None:
            page.updated_at = data.updated_at.replace(tzinfo=None)

    await session.flush()
    # RADD-713: only when the body moved — a rename or a drag cannot change links.
    if "body" in changed:
        await backlinks.reindex(session, page)
        await page_mentions.reindex(session, page)
    payload = {"title": page.title, "version": page.version, "changed": changed}
    diff = await _page_diff(session, page, before, changed)
    if moved:
        await _emit_page(session, PageEvent.PAGE_MOVED, page, actor_id, payload, diff)
    if set(changed) - {"parent_id", "position"}:
        await _emit_page(session, PageEvent.PAGE_UPDATED, page, actor_id, payload, diff)
        # RADD-719: editing auto-watches. Who hears about the edit is notify's
        # decision, off this event (spec 118).
        await page_watchers.watch(session, page.id, actor_id)
    return page


async def archive_page(session: AsyncSession, page_id: uuid.UUID, actor_id: uuid.UUID) -> None:
    page = await get_page(session, page_id)
    if page.archived_at is None:
        page.archived_at = utcnow()
        await session.flush()
        await _emit_page(
            session, PageEvent.PAGE_DELETED, page, actor_id,
            {"title": page.title, "hard": False},
        )


async def unarchive_page(
    session: AsyncSession, page_id: uuid.UUID, actor_id: uuid.UUID
) -> Page:
    """Clear `archived_at` on the page AND every archived ancestor — the tree
    hides a page under an archived ancestor (RADD-1228). Archived siblings stay
    archived."""
    page = await get_page(session, page_id)
    space_rows = await _space_rows(session, page.space_id)
    paths_before = core.page_paths(space_rows)
    by_id = {row.id: row for row in space_rows}
    parent_of = {row.id: row.parent_id for row in space_rows}
    chain = [page, *(by_id[ancestor] for ancestor in core.ancestor_ids(parent_of, page.id))]
    for row in chain:
        if row.archived_at is not None:
            # RADD-1233: while it was archived a live sibling may have taken
            # its name; the restored page yields, and the event says so.
            payload: dict = {"title": row.title, "action": RestoreKind.UNARCHIVE}
            previous = row.slug
            if await _reslug(session, row, row.slug):
                payload["slug_was"] = previous
            row.archived_at = None
            await session.flush()
            await _emit_page(session, PageEvent.PAGE_RESTORED, row, actor_id, payload)
    _remember_paths(session, space_rows, paths_before)
    return page


async def hard_delete_page(
    session: AsyncSession, page_id: uuid.UUID, actor_id: uuid.UUID
) -> None:
    page = await get_page(session, page_id)
    live_children = await session.scalar(
        select(func.count()).select_from(Page).where(
            Page.parent_id == page.id, Page.archived_at.is_(None)
        )
    )
    if live_children:
        raise ConflictError(
            PageEntity.PAGE, reason=f"page has {live_children} non-archived child page(s)"
        )
    # BEFORE the row goes: the kernel resolves the page SUBJECT by reading the row
    # (RADD-923). Outbox row and deletion commit together, so the order is local.
    await _emit_page(
        session, PageEvent.PAGE_DELETED, page, actor_id,
        {"title": page.title, "hard": True},
    )
    # RADD-717: page comments carry no FK, so they go with the page explicitly.
    from radd.modules.comments import service as comments_service
    from radd.modules.comments.types import CommentParentType

    await comments_service.delete_for_parent(session, CommentParentType.PAGE.value, page.id)
    await session.delete(page)  # versions/links/archived subtree go via FK CASCADE
    await session.flush()


async def _depths(session: AsyncSession, space_id: uuid.UUID) -> dict[uuid.UUID, int]:
    """Page id -> depth in the space's tree (root = 0)."""
    parent_of = {row.id: row.parent_id for row in await _space_rows(session, space_id)}
    return {page_id: len(core.ancestor_ids(parent_of, page_id)) for page_id in parent_of}


async def _bulk(
    session: AsyncSession,
    space_id: uuid.UUID,
    page_ids: list[uuid.UUID],
    guard,
    *,
    deepest_first: bool,
    live_reason: str,
    act,
) -> tuple[list[uuid.UUID], list[tuple[uuid.UUID, str]]]:
    """RADD-1249: act on a selection of ARCHIVED pages one at a time, in tree
    order. `guard(page_id)` is the router's per-page gate; a refusal (or a live
    page, `live_reason`) skips that page with its reason, never the selection."""
    depths = await _depths(session, space_id)
    order = -1 if deepest_first else 1
    done: list[uuid.UUID] = []
    skipped: list[tuple[uuid.UUID, str]] = []
    for page_id in sorted(dict.fromkeys(page_ids), key=lambda pid: order * depths.get(pid, 0)):
        try:
            page = await guard(page_id)
            if page.space_id != space_id:
                raise NotFoundError(PageEntity.PAGE, page_id)
            if page.archived_at is None:
                skipped.append((page_id, live_reason))
                continue
            await act(page_id)
            done.append(page_id)
        except RaddError as error:
            skipped.append((page_id, str(error)))
    return done, skipped


async def bulk_restore_pages(
    session: AsyncSession, space_id: uuid.UUID, page_ids: list[uuid.UUID], actor, guard
) -> tuple[list[uuid.UUID], list[tuple[uuid.UUID, str]]]:
    """Ancestors first, so a child's chain-restore (RADD-1228) never precedes its
    parent's own."""
    return await _bulk(
        session, space_id, page_ids, guard, deepest_first=False, live_reason="already live",
        act=lambda page_id: unarchive_page(session, page_id, actor.id),
    )


async def bulk_delete_pages(
    session: AsyncSession, space_id: uuid.UUID, page_ids: list[uuid.UUID], actor, guard
) -> tuple[list[uuid.UUID], list[tuple[uuid.UUID, str]]]:
    """Deepest first: otherwise the parent's FK cascade removes a selected child
    the identity map still holds, and its own delete hits a row that is gone."""
    return await _bulk(
        session, space_id, page_ids, guard, deepest_first=True,
        live_reason="not archived — archive it first",
        act=lambda page_id: hard_delete_page(session, page_id, actor.id),
    )


async def page_read(session: AsyncSession, page: Page) -> PageRead:
    """Full page + its space + the ancestor breadcrumb trail (root first)."""
    space = await get_space(session, page.space_id)
    by_id = {row.id: row for row in await _space_rows(session, page.space_id)}
    row_paths = core.page_paths(by_id.values())
    parent_of = {row_id: row.parent_id for row_id, row in by_id.items()}
    trail = [
        PageBreadcrumb(
            id=ancestor.id,
            number=ancestor.number,
            title=ancestor.title,
            slug=ancestor.slug,
            path=row_paths[ancestor.id],
        )
        for ancestor in (by_id[ancestor_id] for ancestor_id in core.ancestor_ids(parent_of, page.id))
    ]
    label_names = [label.name for label in await page_labels.labels_of(session, page.id)]
    return PageRead(
        id=page.id,
        number=page.number,
        labels=label_names,
        space_id=page.space_id,
        parent_id=page.parent_id,
        title=page.title,
        slug=page.slug,
        path=row_paths.get(page.id, page.slug),
        body=page.body,
        position=page.position,
        version=page.version,
        created_by=page.created_by,
        updated_by=page.updated_by,
        archived_at=page.archived_at,
        created_at=page.created_at,
        updated_at=page.updated_at,
        space=PageSpaceRead.model_validate(space),
        breadcrumb=list(reversed(trail)),
    )


# --- versions ---


async def list_versions(session: AsyncSession, page_id: uuid.UUID) -> list[PageVersion]:
    await get_page(session, page_id)
    result = await session.execute(
        select(PageVersion)
        .where(PageVersion.page_id == page_id)
        .order_by(PageVersion.version.desc())
    )
    return list(result.scalars())


async def write_version(
    session: AsyncSession,
    page_id: uuid.UUID,
    *,
    version: int,
    title: str,
    body: str,
    author_id: uuid.UUID,
    created_at: datetime | None = None,
    permissions: "frozenset" = frozenset(),
) -> PageVersion:
    """Insert one historical revision directly (spec 117; page.manage only) —
    replaying through `update_page` would fire N events and 2N reindexes.
    Off-by-one: a row holds the PREVIOUS content, so an importer writes revisions
    1..N-1 here and N as the live row (`page.version = N`).
    """
    if not _may_import(permissions):
        raise ForbiddenError("page.manage is required to write history directly")
    await get_page(session, page_id)
    row = PageVersion(
        page_id=page_id, version=version, title=title, body=body, author_id=author_id
    )
    if created_at is not None:
        row.created_at = created_at.replace(tzinfo=None)
    session.add(row)
    await session.flush()
    return row


async def get_version(
    session: AsyncSession, page_id: uuid.UUID, version: int
) -> PageVersion:
    row = await session.scalar(
        select(PageVersion).where(
            PageVersion.page_id == page_id, PageVersion.version == version
        )
    )
    if row is None:
        raise NotFoundError(PageEntity.PAGE, f"{page_id} v{version}")
    return row


async def restore_version(
    session: AsyncSession, page_id: uuid.UUID, version: int, actor_id: uuid.UUID
) -> Page:
    """Restore = a NEW version whose content is the old one (history is linear)."""
    page = await get_page(session, page_id)
    snapshot = await get_version(session, page_id, version)
    _snapshot_current(session, page)
    page.title = snapshot.title
    page.body = snapshot.body
    page.version += 1
    page.updated_by = actor_id
    await session.flush()
    # A restore replaces the body: both derived indexes must follow it.
    await backlinks.reindex(session, page)
    await page_mentions.reindex(session, page)
    await _emit_page(
        session, PageEvent.PAGE_RESTORED, page, actor_id,
        {
            "title": page.title,
            "action": RestoreKind.VERSION,
            "restored_version": version,
            "version": page.version,
        },
    )
    return page


async def _actor_name(session: AsyncSession, actor_id: uuid.UUID) -> str:
    """For `{{author}}`; empty rather than raising, so a template still renders."""
    from radd.modules.auth.models import User

    user = await session.get(User, actor_id)
    return user.name if user else ""

