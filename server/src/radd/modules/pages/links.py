"""Issue ↔ doc-page links (spec 43).

Items are resolved by their canonical key via the items module's public
service; hydration (key/title/state) goes through project + workflow
services — never another module's tables directly.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, NotFoundError
from radd.modules.auth import authz
from radd.modules.auth.models import User
from radd.modules.events import service as events
from radd.modules.items import service as items_service
from radd.modules.workflow import service as workflow_service
from radd.modules.projects import service as projects_service

from .models import Page, PageSpace, ItemPageLink
from .schemas import PageLinkedItem, ItemPageRef
from .service import get_page
from .types import PageEntity, PageEvent


async def _emit_link(
    session: AsyncSession,
    event_type: PageEvent,
    page: Page,
    item_id: uuid.UUID,
    item_key: str,
    actor_id: uuid.UUID,
) -> None:
    await events.emit(
        session,
        event_type=event_type,
        entity_type=PageEntity.PAGE,
        entity_id=page.id,
        actor_id=actor_id,
        subjects={"item": item_id},
        payload={"title": page.title},
    )


async def link_item(
    session: AsyncSession, page_id: uuid.UUID, item_key: str, actor: User
) -> PageLinkedItem:
    """Link an item by its display key. Requires item.read on the item's project
    (checked here — the router has already checked page.write on the page)."""
    page = await get_page(session, page_id)
    item = await items_service.find_item_by_key(session, item_key)
    if item is None:
        raise NotFoundError("item", item_key)
    project = await projects_service.get_project(session, item.project_id)
    await authz.require(session, actor, authz.Permission.ITEM_READ, project=project)
    existing = await session.get(ItemPageLink, (item.id, page.id))
    if existing is not None:
        raise ConflictError("page_link", item_key)
    session.add(ItemPageLink(item_id=item.id, page_id=page.id, created_by=actor.id))
    await session.flush()
    key = f"{project.key}-{item.number}"
    await _emit_link(
        session, PageEvent.LINK_CREATED, page, item.id, key, actor.id
    )
    state = await workflow_service.get_state(session, item.state_id)
    return PageLinkedItem(
        item_id=item.id,
        key=key,
        title=item.title,
        state=state.name,
        state_category=state.category,
    )


async def unlink_item(
    session: AsyncSession, page_id: uuid.UUID, item_id: uuid.UUID, actor_id: uuid.UUID
) -> None:
    page = await get_page(session, page_id)
    link = await session.get(ItemPageLink, (item_id, page_id))
    if link is None:
        raise NotFoundError("page_link", item_id)
    await session.delete(link)
    await session.flush()
    await _emit_link(
        session, PageEvent.LINK_DELETED, page, item_id, "", actor_id
    )


async def linked_items(
    session: AsyncSession, page_id: uuid.UUID, actor: User
) -> list[PageLinkedItem]:
    """Items linked to a page, hydrated for display and filtered to projects
    the caller may read (item.read)."""
    await get_page(session, page_id)
    item_ids = list(
        (
            await session.execute(
                select(ItemPageLink.item_id).where(ItemPageLink.page_id == page_id)
            )
        ).scalars()
    )
    if not item_ids:
        return []
    items = await items_service.items_by_ids(session, item_ids)
    projects = {
        project.id: project
        for project in [
            await projects_service.get_project(session, pid)
            for pid in {item.project_id for item in items.values()}
        ]
    }
    permissions = await authz.permissions_for_projects(session, actor, list(projects.values()))
    states = await workflow_service.states_by_ids(
        session, {item.state_id for item in items.values()}
    )
    results: list[PageLinkedItem] = []
    for item_id in item_ids:
        item = items.get(item_id)
        if item is None:
            continue
        if not authz.holds_base(permissions.get(item.project_id, frozenset()), authz.Permission.ITEM_READ):
            continue
        project = projects[item.project_id]
        state = states.get(item.state_id)
        results.append(
            PageLinkedItem(
                item_id=item.id,
                key=f"{project.key}-{item.number}",
                title=item.title,
                state=state.name if state else "",
                state_category=state.category if state else "",
            )
        )
    return sorted(results, key=lambda linked: linked.key)


async def pages_for_item(session: AsyncSession, item_id: uuid.UUID) -> list[ItemPageRef]:
    """Live (non-archived) pages linked to an item — the issue page's Docs row."""
    rows = await session.execute(
        select(Page, PageSpace.name)
        .join(ItemPageLink, ItemPageLink.page_id == Page.id)
        .join(PageSpace, PageSpace.id == Page.space_id)
        .where(ItemPageLink.item_id == item_id, Page.archived_at.is_(None))
        .order_by(Page.title)
    )
    return [
        ItemPageRef(
            page_id=page.id, space_id=page.space_id, title=page.title, space_name=space_name
        )
        for page, space_name in rows.all()
    ]
