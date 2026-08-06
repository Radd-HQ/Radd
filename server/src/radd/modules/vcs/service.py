import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import NotFoundError
from radd.modules.events import service as events
from radd.modules.items import service as items_service
from radd.modules.projects import service as projects_service

from .models import ItemVcsLink
from .schemas import VcsLinkCreate
from .types import VcsEntity, VcsEvent, VcsProvider, VcsRefType
from radd.clock import utcnow


async def link_vcs(
    session: AsyncSession,
    item_id: uuid.UUID,
    data: VcsLinkCreate,
    actor_id: uuid.UUID | None = None,
) -> ItemVcsLink:
    link = ItemVcsLink(
        item_id=item_id,
        ref_type=data.ref_type.value,
        provider=data.provider.value,
        title=data.title,
        url=data.url,
        status=data.status,
        external_id=data.external_id,
        created_by=actor_id,
    )
    session.add(link)
    await session.flush()
    await _emit(session, VcsEvent.LINKED, link, actor_id)
    return link


async def unlink_vcs(
    session: AsyncSession, link_id: uuid.UUID, actor_id: uuid.UUID | None = None
) -> None:
    link = await get_vcs_link(session, link_id)
    await session.delete(link)
    await session.flush()
    await _emit(session, VcsEvent.UNLINKED, link, actor_id)


async def get_vcs_link(session: AsyncSession, link_id: uuid.UUID) -> ItemVcsLink:
    link = await session.get(ItemVcsLink, link_id)
    if link is None:
        raise NotFoundError(VcsEntity.VCS_LINK, link_id)
    return link


async def list_for_item(session: AsyncSession, item_id: uuid.UUID) -> list[ItemVcsLink]:
    result = await session.execute(
        select(ItemVcsLink).where(ItemVcsLink.item_id == item_id).order_by(ItemVcsLink.created_at)
    )
    return list(result.scalars())


async def upsert_vcs_link(
    session: AsyncSession,
    item_id: uuid.UUID,
    *,
    provider: VcsProvider,
    ref_type: VcsRefType,
    external_id: str,
    title: str,
    url: str,
    status: str = "",
    actor_id: uuid.UUID | None = None,
) -> ItemVcsLink:
    """The CONNECTOR SEAM: the write-path GitLab/GitHub/Forgejo connectors call to keep an
    item's dev panel in sync. When `external_id` is set, find the existing row matched by
    (item_id, provider, external_id) and update it in place (title/url/status/ref_type);
    otherwise create a fresh link. Emits vcs.updated on update, vcs.linked on create."""
    existing = None
    if external_id != "":
        existing = await session.scalar(
            select(ItemVcsLink).where(
                ItemVcsLink.item_id == item_id,
                ItemVcsLink.provider == provider.value,
                ItemVcsLink.external_id == external_id,
            )
        )
    if existing is not None:
        existing.ref_type = ref_type.value
        existing.title = title
        existing.url = url
        existing.status = status
        await session.flush()
        await _emit(session, VcsEvent.UPDATED, existing, actor_id)
        return existing
    link = ItemVcsLink(
        item_id=item_id,
        ref_type=ref_type.value,
        provider=provider.value,
        title=title,
        url=url,
        status=status,
        external_id=external_id,
        created_by=actor_id,
    )
    session.add(link)
    await session.flush()
    await _emit(session, VcsEvent.LINKED, link, actor_id)
    return link


async def _emit(
    session: AsyncSession, event_type: VcsEvent, link: ItemVcsLink, actor_id: uuid.UUID | None
) -> None:
    item = await items_service.require_item(session, link.item_id)
    project = await projects_service.get_project(session, item.project_id)
    await events.emit(
        session,
        event_type=event_type,
        entity_type=VcsEntity.VCS_LINK,
        entity_id=link.id,
        actor_id=actor_id,
        subjects={"item": link.item_id},
        payload={
            "ref_type": link.ref_type,
            "provider": link.provider,
            "title": link.title,
            "url": link.url,
            "status": link.status,
        },
    )


async def set_ci_state(
    session: AsyncSession,
    *,
    provider: str,
    external_ids: Sequence[str],
    ci_state: str,
    ci_url: str = "",
) -> int:
    """Stamp the latest CI result onto every link for these refs (spec 111).

    Keyed by (provider, external_id) rather than by item: one workflow run
    concerns a ref, and that ref may be linked from several items — all of them
    want the same answer.
    """
    if not external_ids:
        return 0
    rows = await session.execute(
        select(ItemVcsLink).where(
            ItemVcsLink.provider == provider, ItemVcsLink.external_id.in_(list(external_ids))
        )
    )
    links = list(rows.scalars())
    for link in links:
        link.ci_state = ci_state
        link.ci_url = ci_url
        link.ci_updated_at = utcnow()
    await session.flush()
    return len(links)
