import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import NotFoundError
from radd.modules.events import service as events
from radd.modules.items import service as items_service
from radd.modules.projects import service as projects_service

from .models import ItemWebLink
from .schemas import WebLinkCreate, WebLinkUpdate
from .types import WebLinkEntity, WebLinkEvent


async def create_web_link(
    session: AsyncSession,
    item_id: uuid.UUID,
    data: WebLinkCreate,
    actor_id: uuid.UUID | None = None,
) -> ItemWebLink:
    link = ItemWebLink(
        item_id=item_id,
        url=data.url,
        title=data.title,
        category=data.category.value,
        created_by=actor_id,
    )
    session.add(link)
    await session.flush()
    await _emit(session, WebLinkEvent.CREATED, link, actor_id)
    return link


async def update_web_link(
    session: AsyncSession,
    link_id: uuid.UUID,
    data: WebLinkUpdate,
    actor_id: uuid.UUID | None = None,
) -> ItemWebLink:
    link = await get_web_link(session, link_id)
    if data.url is not None:
        link.url = data.url
    if data.title is not None:
        link.title = data.title
    if data.category is not None:
        link.category = data.category.value
    await session.flush()
    await _emit(session, WebLinkEvent.UPDATED, link, actor_id)
    return link


async def delete_web_link(
    session: AsyncSession, link_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> None:
    link = await get_web_link(session, link_id)
    await session.delete(link)
    await session.flush()
    await _emit(session, WebLinkEvent.DELETED, link, actor_id)


async def get_web_link(session: AsyncSession, link_id: uuid.UUID) -> ItemWebLink:
    link = await session.get(ItemWebLink, link_id)
    if link is None:
        raise NotFoundError(WebLinkEntity.WEB_LINK, link_id)
    return link


async def list_for_item(session: AsyncSession, item_id: uuid.UUID) -> list[ItemWebLink]:
    result = await session.execute(
        select(ItemWebLink)
        .where(ItemWebLink.item_id == item_id)
        .order_by(ItemWebLink.created_at)
    )
    return list(result.scalars())


async def _emit(
    session: AsyncSession,
    event_type: WebLinkEvent,
    link: ItemWebLink,
    actor_id: uuid.UUID | None,
) -> None:
    item = await items_service.require_item(session, link.item_id)
    await projects_service.get_project(session, item.project_id)
    await events.emit(
        session,
        event_type=event_type,
        entity_type=WebLinkEntity.WEB_LINK,
        entity_id=link.id,
        actor_id=actor_id,
        subjects={"item": link.item_id},
        payload={
            "url": link.url,
            "title": link.title,
            "category": link.category,
        },
    )
