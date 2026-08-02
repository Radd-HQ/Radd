"""Doc pages + version history (spec 43). Space CRUD lives in spaces.py.

Optimistic concurrency: a PATCH carrying `expected_version` 409s when stale;
content changes snapshot the PREVIOUS content into doc_page_versions and bump
`version`. Parent moves run the pure cycle guard in core.py.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, NotFoundError
from radd.modules.events import service as events

from . import core
from .models import DocPage, DocPageVersion
from .schemas import (
    DocBreadcrumb,
    DocPageCreate,
    DocPageRead,
    DocPageSummary,
    DocPageUpdate,
    DocSpaceRead,
)
from .spaces import get_space
from .types import DocEntity, DocEvent, RestoreKind

__all__ = ["get_space"]  # re-exported: the space half of the module's seam


def _now() -> datetime:
    """Naive UTC, matching the server-side now() used for created_at/updated_at."""
    return datetime.now(UTC).replace(tzinfo=None)


async def _emit_page(
    session: AsyncSession,
    event_type: DocEvent,
    page: DocPage,
    actor_id: uuid.UUID,
    payload: dict,
) -> None:
    await events.emit(
        session,
        event_type=event_type,
        entity_type=DocEntity.PAGE,
        entity_id=page.id,
        actor_id=actor_id,
        payload=payload,
    )


async def get_page(session: AsyncSession, page_id: uuid.UUID) -> DocPage:
    page = await session.get(DocPage, page_id)
    if page is None:
        raise NotFoundError(DocEntity.PAGE, page_id)
    return page


async def _space_rows(session: AsyncSession, space_id: uuid.UUID) -> list[DocPage]:
    result = await session.execute(select(DocPage).where(DocPage.space_id == space_id))
    return list(result.scalars())


async def list_pages(
    session: AsyncSession, space_id: uuid.UUID, *, include_archived: bool = False
) -> list[DocPageSummary]:
    """Flat tree rows (client builds the hierarchy). Archived subtrees are
    pruned unless `include_archived` (the doc.manage restore listing)."""
    rows = await _space_rows(session, space_id)
    parent_of = {row.id: row.parent_id for row in rows}
    if include_archived:
        visible = set(parent_of)
    else:
        archived = {row.id for row in rows if row.archived_at is not None}
        visible = core.visible_page_ids(parent_of, archived)
    children: set[uuid.UUID] = {
        row.parent_id for row in rows if row.parent_id is not None and row.id in visible
    }
    return sorted(
        (
            DocPageSummary(
                id=row.id,
                parent_id=row.parent_id,
                title=row.title,
                position=row.position,
                has_children=row.id in children,
                updated_at=row.updated_at,
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
        select(func.max(DocPage.position)).where(
            DocPage.space_id == space_id, DocPage.parent_id == parent_id
        )
    )
    return (highest or 0) + 1


async def create_page(
    session: AsyncSession, data: DocPageCreate, actor_id: uuid.UUID
) -> DocPage:
    space = await get_space(session, data.space_id)
    if data.parent_id is not None:
        parent = await get_page(session, data.parent_id)
        if parent.space_id != space.id:
            raise ConflictError(DocEntity.PAGE, reason="parent page is in a different space")
    position = (
        data.position
        if data.position is not None
        else await _next_position(session, space.id, data.parent_id)
    )
    page = DocPage(
        space_id=space.id,
        parent_id=data.parent_id,
        title=data.title,
        body=data.body,
        position=position,
        created_by=actor_id,
        updated_by=actor_id,
    )
    session.add(page)
    await session.flush()
    await _emit_page(
        session, DocEvent.PAGE_CREATED, page, actor_id,
        {"title": page.title, "space_id": str(space.id)},
    )
    return page


async def update_page(
    session: AsyncSession, page_id: uuid.UUID, data: DocPageUpdate, actor_id: uuid.UUID
) -> DocPage:
    page = await get_page(session, page_id)
    if data.expected_version is not None and data.expected_version != page.version:
        raise ConflictError(
            DocEntity.PAGE,
            reason=f"version conflict: page is at version {page.version}",
        )

    changed: list[str] = []
    moved = False
    if "parent_id" in data.model_fields_set and data.parent_id != page.parent_id:
        if data.parent_id is not None:
            parent = await get_page(session, data.parent_id)
            if parent.space_id != page.space_id:
                raise ConflictError(DocEntity.PAGE, reason="parent page is in a different space")
            parent_of = {
                row.id: row.parent_id for row in await _space_rows(session, page.space_id)
            }
            if core.would_create_cycle(page.id, data.parent_id, parent_of):
                raise ConflictError(DocEntity.PAGE, reason="move would create a cycle")
        page.parent_id = data.parent_id
        changed.append("parent_id")
        moved = True
    if data.position is not None and data.position != page.position:
        page.position = data.position
        changed.append("position")
        moved = True

    if core.should_snapshot(page.title, page.body, data.title, data.body):
        session.add(
            DocPageVersion(
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
        page.version += 1
        page.updated_by = actor_id

    await session.flush()
    payload = {"title": page.title, "version": page.version, "changed": changed}
    if moved:
        await _emit_page(session, DocEvent.PAGE_MOVED, page, actor_id, payload)
    if set(changed) - {"parent_id", "position"}:
        await _emit_page(session, DocEvent.PAGE_UPDATED, page, actor_id, payload)
    return page


async def archive_page(session: AsyncSession, page_id: uuid.UUID, actor_id: uuid.UUID) -> None:
    page = await get_page(session, page_id)
    if page.archived_at is None:
        page.archived_at = _now()
        await session.flush()
        await _emit_page(
            session, DocEvent.PAGE_DELETED, page, actor_id,
            {"title": page.title, "hard": False},
        )


async def unarchive_page(
    session: AsyncSession, page_id: uuid.UUID, actor_id: uuid.UUID
) -> DocPage:
    page = await get_page(session, page_id)
    if page.archived_at is not None:
        page.archived_at = None
        await session.flush()
        await _emit_page(
            session, DocEvent.PAGE_RESTORED, page, actor_id,
            {"title": page.title, "action": RestoreKind.UNARCHIVE},
        )
    return page


async def hard_delete_page(
    session: AsyncSession, page_id: uuid.UUID, actor_id: uuid.UUID
) -> None:
    page = await get_page(session, page_id)
    live_children = await session.scalar(
        select(func.count()).select_from(DocPage).where(
            DocPage.parent_id == page.id, DocPage.archived_at.is_(None)
        )
    )
    if live_children:
        raise ConflictError(
            DocEntity.PAGE, reason=f"page has {live_children} non-archived child page(s)"
        )
    await session.delete(page)  # versions/links/archived subtree go via FK CASCADE
    await session.flush()
    await _emit_page(
        session, DocEvent.PAGE_DELETED, page, actor_id,
        {"title": page.title, "hard": True},
    )


async def page_read(session: AsyncSession, page: DocPage) -> DocPageRead:
    """Full page + its space + the ancestor breadcrumb trail (root first)."""
    space = await get_space(session, page.space_id)
    by_id = {row.id: row for row in await _space_rows(session, page.space_id)}
    trail: list[DocBreadcrumb] = []
    current = page.parent_id
    for _ in range(len(by_id) + 1):
        if current is None:
            break
        ancestor = by_id.get(current)
        if ancestor is None:
            break
        trail.append(DocBreadcrumb(id=ancestor.id, title=ancestor.title))
        current = ancestor.parent_id
    return DocPageRead(
        id=page.id,
        space_id=page.space_id,
        parent_id=page.parent_id,
        title=page.title,
        body=page.body,
        position=page.position,
        version=page.version,
        created_by=page.created_by,
        updated_by=page.updated_by,
        archived_at=page.archived_at,
        created_at=page.created_at,
        updated_at=page.updated_at,
        space=DocSpaceRead.model_validate(space),
        breadcrumb=list(reversed(trail)),
    )


# --- versions ---


async def list_versions(session: AsyncSession, page_id: uuid.UUID) -> list[DocPageVersion]:
    await get_page(session, page_id)
    result = await session.execute(
        select(DocPageVersion)
        .where(DocPageVersion.page_id == page_id)
        .order_by(DocPageVersion.version.desc())
    )
    return list(result.scalars())


async def get_version(
    session: AsyncSession, page_id: uuid.UUID, version: int
) -> DocPageVersion:
    row = await session.scalar(
        select(DocPageVersion).where(
            DocPageVersion.page_id == page_id, DocPageVersion.version == version
        )
    )
    if row is None:
        raise NotFoundError(DocEntity.PAGE, f"{page_id} v{version}")
    return row


async def restore_version(
    session: AsyncSession, page_id: uuid.UUID, version: int, actor_id: uuid.UUID
) -> DocPage:
    """Restore = a NEW version whose content is the old one (history is linear)."""
    page = await get_page(session, page_id)
    snapshot = await get_version(session, page_id, version)
    session.add(
        DocPageVersion(
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
    await _emit_page(
        session, DocEvent.PAGE_RESTORED, page, actor_id,
        {
            "title": page.title,
            "action": RestoreKind.VERSION,
            "restored_version": version,
            "version": page.version,
        },
    )
    return page
