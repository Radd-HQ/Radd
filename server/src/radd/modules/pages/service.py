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

from radd.exceptions import ConflictError, ForbiddenError, NotFoundError
from radd.modules.events import service as events

from . import (
    backlinks,
    core,
    labels as page_labels,
    mentions as page_mentions,
    templates as page_templates,
    watchers as page_watchers,
)
from .core import page_slugify
from .models import Page, PageSpace, PageVersion

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

__all__ = ["get_space"]  # re-exported: the space half of the module's seam



async def _emit_page(
    session: AsyncSession,
    event_type: PageEvent,
    page: Page,
    actor_id: uuid.UUID,
    payload: dict,
) -> None:
    """Every page event names its PAGE and its SPACE as subjects (spec 118).

    The kernel writes both refs from the ids (RADD-923), so a consumer gets the
    slugs it needs to link and the space id a subscription is matched on without
    this module handing anyone a shape it built itself. The remaining payload
    keys are page-event DATA — what changed, and whether a delete was hard —
    which is the split the subject seam draws.
    """
    await events.emit(
        session,
        event_type=event_type,
        entity_type=PageEntity.PAGE,
        entity_id=page.id,
        actor_id=actor_id,
        payload=payload,
        subjects={"page": page.id, "page_space": page.space_id},
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
    """Flat tree rows (client builds the hierarchy). Archived subtrees are
    pruned unless `include_archived` (the page.manage restore listing).

    `actor` drops the pages they may not read (RADD-792). Optional so internal
    callers (export, backlinks) keep the unfiltered tree; every ACTOR-facing
    caller passes one, because a restricted page listed in the rail would leak
    its title, which is usually the part worth restricting.
    """
    rows = await _space_rows(session, space_id)
    if actor is not None:
        from . import page_access

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
    # RADD-718: one query for the whole tree. A query per row is how a 200-page
    # space becomes slow the moment labels are shown in the rail.
    label_names = await page_labels.labels_for_pages(session, [row.id for row in rows])
    return sorted(
        (
            PageSummary(
                id=row.id,
                parent_id=row.parent_id,
                title=row.title,
                slug=row.slug,
                position=row.position,
                has_children=row.id in children,
                updated_at=row.updated_at,
                labels=label_names.get(row.id, []),
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


async def _free_slug(
    session: AsyncSession,
    space_id: uuid.UUID,
    candidate: str,
    *,
    exclude_id: uuid.UUID | None = None,
) -> str:
    """`candidate` made unique within the space (RADD-702). The taken set is read
    per call rather than caught as an IntegrityError: a 409 on 'a page over there
    already uses this URL' would be a strange thing to show someone who only
    typed a title."""
    query = select(Page.slug).where(Page.space_id == space_id)
    if exclude_id is not None:
        query = query.where(Page.id != exclude_id)
    taken = set((await session.execute(query)).scalars())
    return core.unique_slug(page_slugify(candidate), taken)


async def resolve_page_by_slug(session: AsyncSession, space_slug: str, page_slug: str) -> Page:
    """`/pages/<space>/<page>` → the page. Both segments accept an ID as well as
    a slug, which is what keeps every UUID URL ever shared alive (RADD-702)."""
    space = await _space_by_slug_or_id(session, space_slug)
    page = (
        await session.execute(
            select(Page).where(Page.space_id == space.id, Page.slug == page_slug)
        )
    ).scalar_one_or_none()
    if page is None:
        page = await _page_by_id_text(session, page_slug, space.id)
    if page is None:
        raise NotFoundError(PageEntity.PAGE, f"{space_slug}/{page_slug}")
    return page


async def _space_by_slug_or_id(session: AsyncSession, value: str) -> PageSpace:
    space = (
        await session.execute(select(PageSpace).where(PageSpace.slug == value))
    ).scalar_one_or_none()
    if space is not None:
        return space
    try:
        return await get_space(session, uuid.UUID(value))
    except (ValueError, AttributeError):
        raise NotFoundError(PageEntity.SPACE, value) from None


async def _page_by_id_text(
    session: AsyncSession, value: str, space_id: uuid.UUID
) -> Page | None:
    try:
        page_id = uuid.UUID(value)
    except ValueError:
        return None
    page = (
        await session.execute(
            select(Page).where(Page.id == page_id, Page.space_id == space_id)
        )
    ).scalar_one_or_none()
    return page


def _may_import(permissions: "frozenset" = frozenset()) -> bool:
    """Spec 117. The import overrides (author, timestamps, external identity) are
    honored only for a caller that already holds `page.manage` in the space.

    Deferred import: `auth` loads before `pages`, and taking the enum at module
    scope would invert that. Pages have no project, so `PROJECT_MANAGE` — the atom
    `comments` gates its own overrides on — is not the right one here.
    """
    from radd.modules.auth.types import Permission

    return Permission.PAGE_MANAGE in permissions


async def find_by_external(
    session: AsyncSession, external_source: str, external_id: str
) -> Page | None:
    """The page a previous import made from that foreign row, if any (spec 117).

    This is what makes re-import an upsert instead of a duplicate, and what lets a
    link resolve to a page some ENTIRELY OTHER run created — the case the run
    ledger cannot answer, because it is scoped to one run and its rollback
    deletes it.
    """
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
    position = (
        data.position
        if data.position is not None
        else await _next_position(session, space.id, data.parent_id)
    )
    body = data.body
    if not body and data.template:
        # RADD-712. An explicit body wins — naming a template AND supplying a
        # body means the caller has decided, and silently overwriting it would be
        # the surprising behaviour.
        template = await page_templates.by_name(session, data.template)
        author = await _actor_name(session, actor_id)
        body = page_templates.render(template.body, title=data.title, author=author)
    # Spec 117. An import states the author and the dates; everything else is the
    # actor and `now`. Gated together because they are one act — a page credited
    # to its real author but stamped today is not more honest than one stamped
    # correctly and credited wrongly.
    importing = _may_import(permissions)
    author_id = data.author_id if (importing and data.author_id) else actor_id
    page = Page(
        space_id=space.id,
        parent_id=data.parent_id,
        title=data.title,
        slug=await _free_slug(session, space.id, data.slug or page_slugify(data.title)),
        body=body,
        position=position,
        created_by=author_id,
        updated_by=author_id,
        external_source=data.external_source if importing else "",
        external_id=data.external_id if importing else "",
    )
    # Naive UTC, matching the columns' server defaults — the same conversion
    # `comments.create_authorized_comment` does for its backdated rows.
    if importing and data.created_at is not None:
        page.created_at = data.created_at.replace(tzinfo=None)
    if importing and (data.updated_at or data.created_at) is not None:
        page.updated_at = (data.updated_at or data.created_at).replace(tzinfo=None)
    session.add(page)
    await session.flush()
    await backlinks.reindex(session, page)  # RADD-713
    await page_mentions.reindex(session, page)  # RADD-943
    # `space_id` is gone from the payload: the `page_space` SUBJECT carries it,
    # as a ref with a name and a slug rather than a bare uuid string nobody
    # could render (spec 118).
    await _emit_page(session, PageEvent.PAGE_CREATED, page, actor_id, {"title": page.title})
    return page


async def update_page(
    session: AsyncSession,
    page_id: uuid.UUID,
    data: PageUpdate,
    actor_id: uuid.UUID,
    *,
    permissions: "frozenset" = frozenset(),
) -> Page:
    page = await get_page(session, page_id)
    if data.expected_version is not None and data.expected_version != page.version:
        raise ConflictError(
            PageEntity.PAGE,
            reason=f"version conflict: page is at version {page.version}",
        )

    changed: list[str] = []
    moved = False
    if "parent_id" in data.model_fields_set and data.parent_id != page.parent_id:
        if data.parent_id is not None:
            parent = await get_page(session, data.parent_id)
            if parent.space_id != page.space_id:
                raise ConflictError(PageEntity.PAGE, reason="parent page is in a different space")
            parent_of = {
                row.id: row.parent_id for row in await _space_rows(session, page.space_id)
            }
            if core.would_create_cycle(page.id, data.parent_id, parent_of):
                raise ConflictError(PageEntity.PAGE, reason="move would create a cycle")
        page.parent_id = data.parent_id
        changed.append("parent_id")
        moved = True
    if data.position is not None and data.position != page.position:
        page.position = data.position
        changed.append("position")
        moved = True
    # RADD-702: the slug changes ONLY when asked. A title edit deliberately does
    # not touch it — the URL is a promise to whoever already has the link, and
    # "fixed a typo in the heading" is not a reason to break it.
    # RADD-860: …except a PLACEHOLDER slug. Every UI-created page is born
    # "Untitled" → `untitled-N`, and a URL nobody chose protects nobody — the
    # first REAL title upgrades it. Established slugs stay immovable.
    if data.slug is not None and data.slug != page.slug:
        page.slug = await _free_slug(
            session, page.space_id, page_slugify(data.slug), exclude_id=page.id
        )
        changed.append("slug")
    elif (
        data.title is not None
        and data.title != page.title
        and _PLACEHOLDER_SLUG_RE.fullmatch(page.slug)
        and page_slugify(data.title) not in ("untitled", "page")
    ):
        page.slug = await _free_slug(session, page.space_id, data.title, exclude_id=page.id)
        changed.append("slug")

    if core.should_snapshot(page.title, page.body, data.title, data.body):
        importing = _may_import(permissions)
        # Spec 117: an import writes a page over several passes; those passes are
        # not edits, and letting them consume version numbers collides with the
        # page's real imported history.
        quiet_write = importing and data.suppress_version
        if not quiet_write:
            session.add(
                PageVersion(
                    page_id=page.id,
                    version=page.version,
                    title=page.title,
                    body=page.body,
                    author_id=page.updated_by,
                )
            )
        if data.title is not None and data.title != page.title:
            page.title = data.title
            changed.append("title")
        if data.body is not None and data.body != page.body:
            page.body = data.body
            changed.append("body")
        if not quiet_write:
            page.version += 1
        # Spec 117: a re-import credits the revision's real editor.
        page.updated_by = (
            data.author_id if (importing and data.author_id) else actor_id
        )
        if importing and data.updated_at is not None:
            page.updated_at = data.updated_at.replace(tzinfo=None)

    await session.flush()
    # RADD-713: only when the body moved. A rename or a reposition cannot change
    # what this page links to, and reindexing on every save would put a delete +
    # N inserts behind dragging a page in the tree.
    if "body" in changed:
        await backlinks.reindex(session, page)
        await page_mentions.reindex(session, page)
    payload = {"title": page.title, "version": page.version, "changed": changed}
    if moved:
        await _emit_page(session, PageEvent.PAGE_MOVED, page, actor_id, payload)
    if set(changed) - {"parent_id", "position"}:
        await _emit_page(session, PageEvent.PAGE_UPDATED, page, actor_id, payload)
        # RADD-719. Auto-watch on edit, like items: touching something is the
        # strongest signal you care what happens to it next, and a watch feature
        # nobody opts into has no watchers.
        #
        # Spec 118 removed the fan-out that used to sit beside this line. It was
        # synchronous "because page edits are rare and a consumer would mean a
        # second delivery path to keep correct" — and by the time a space could
        # be SUBSCRIBED to, that second path was exactly what it had become: it
        # knew about watchers and nothing about subscribers, and it ran before
        # the permission gate every item notification passes. The watchers table
        # and its service stay; who hears about the edit is now decided in the
        # one place that decides it for issues (`notify.consumer`), off this
        # event.
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
    page = await get_page(session, page_id)
    if page.archived_at is not None:
        page.archived_at = None
        await session.flush()
        await _emit_page(
            session, PageEvent.PAGE_RESTORED, page, actor_id,
            {"title": page.title, "action": RestoreKind.UNARCHIVE},
        )
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
    # BEFORE the row goes, not after. `_emit_page` names the page as a SUBJECT
    # and the kernel resolves a subject by READING the row (RADD-923), so
    # emitting after the delete + flush resolved it to NULL — the one event about
    # a page nobody can look up afterwards was the one that carried no page. The
    # order is invisible outside this function: the outbox row and the deletion
    # commit together or not at all.
    await _emit_page(
        session, PageEvent.PAGE_DELETED, page, actor_id,
        {"title": page.title, "hard": True},
    )
    # RADD-717: page comments are polymorphic and carry no FK, so they do not
    # cascade — remove them with the page rather than orphaning them.
    from radd.modules.comments import service as comments_service
    from radd.modules.comments.types import CommentParentType

    await comments_service.delete_for_parent(session, CommentParentType.PAGE.value, page.id)
    await session.delete(page)  # versions/links/archived subtree go via FK CASCADE
    await session.flush()


async def page_read(session: AsyncSession, page: Page) -> PageRead:
    """Full page + its space + the ancestor breadcrumb trail (root first)."""
    space = await get_space(session, page.space_id)
    by_id = {row.id: row for row in await _space_rows(session, page.space_id)}
    trail: list[PageBreadcrumb] = []
    current = page.parent_id
    for _ in range(len(by_id) + 1):
        if current is None:
            break
        ancestor = by_id.get(current)
        if ancestor is None:
            break
        trail.append(PageBreadcrumb(id=ancestor.id, title=ancestor.title, slug=ancestor.slug))
        current = ancestor.parent_id
    label_names = [label.name for label in await page_labels.labels_of(session, page.id)]
    return PageRead(
        id=page.id,
        labels=label_names,
        space_id=page.space_id,
        parent_id=page.parent_id,
        title=page.title,
        slug=page.slug,
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
    """Insert one historical revision directly (spec 117).

    History normally accretes as a side effect of `update_page`, and for an
    IMPORT that is the wrong shape: replaying N revisions to reconstruct a history
    that is by definition already final would fire N `page.updated` events, N
    watcher fan-outs and 2N reindex passes per page, to arrive at rows this writes
    in one statement.

    Mind the off-by-one `PageVersion` is built on: a row holds the PREVIOUS
    content — version N's row is written when N+1 becomes current — so an importer
    writes revisions 1..N-1 here and revision N as the live `pages` row, with
    `page.version = N`. Getting it backwards yields a History tab whose newest
    entry duplicates the current body while revision 1 is silently lost.
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
    session.add(
        PageVersion(
            page_id=page.id,
            version=page.version,
            title=page.title,
            body=page.body,
            author_id=page.updated_by,
        )
    )
    page.title = snapshot.title
    page.body = snapshot.body
    page.version += 1
    page.updated_by = actor_id
    await session.flush()
    # A restore replaces the body, so both derived indexes describe the version
    # that was just superseded. RADD-713 missed this leg — the backlinks index
    # has been stale after every restore since it shipped.
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
    """For the `{{author}}` placeholder. Falls back to the empty string rather
    than raising: a template should still render for a service account."""
    from radd.modules.auth.models import User

    user = await session.get(User, actor_id)
    return user.name if user else ""


# --- restricted-row filters for the list surfaces (RADD-792) -----------------


async def drop_restricted_results(session: AsyncSession, actor: "User", results: list):
    """FTS hits the actor may not read, removed. Search is the surface where a
    restriction leaks most cheaply: the snippet and the title are the content."""
    if not results:
        return results
    from . import page_access

    pages = list(
        (
            await session.execute(
                select(Page).where(Page.id.in_([r.page_id for r in results]))
            )
        ).scalars()
    )
    readable = await page_access.readable_page_ids(session, actor, pages)
    return [r for r in results if r.page_id in readable]


async def drop_restricted_labelled(session: AsyncSession, actor: "User", rows: list):
    """The same, for a label index — `radd:label-list` renders these into a page
    that anyone in the space can open."""
    if not rows:
        return rows
    from . import page_access

    pages = list(
        (
            await session.execute(
                select(Page).where(Page.id.in_([row.page_id for row in rows]))
            )
        ).scalars()
    )
    readable = await page_access.readable_page_ids(session, actor, pages)
    return [row for row in rows if row.page_id in readable]
