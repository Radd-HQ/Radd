"""Doc-space CRUD (spec 43). Pages/versions live in service.py."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, NotFoundError
from radd.modules.events import service as events

from . import core
from .models import Page, PageSpace
from .schemas import PageSpaceCreate, PageSpaceRead, PageSpaceUpdate
from .types import PageEntity, PageEvent


async def get_space(session: AsyncSession, space_id: uuid.UUID) -> PageSpace:
    space = await session.get(PageSpace, space_id)
    if space is None:
        raise NotFoundError(PageEntity.SPACE, space_id)
    return space


async def by_slug_or_id(session: AsyncSession, identifier: str) -> PageSpace:
    """Prefer an exact slug, retaining legacy UUID URLs and slug ambiguity rules."""
    space = await session.scalar(select(PageSpace).where(PageSpace.slug == identifier))
    if space is not None:
        return space
    try:
        return await get_space(session, uuid.UUID(identifier))
    except (ValueError, AttributeError):
        raise NotFoundError(PageEntity.SPACE, identifier) from None


async def _slug_clash(
    session: AsyncSession, slug: str, exclude: uuid.UUID | None = None
) -> bool:
    stmt = select(PageSpace.id).where(PageSpace.slug == slug)
    if exclude is not None:
        stmt = stmt.where(PageSpace.id != exclude)
    return (await session.scalar(stmt)) is not None


async def _emit_space(
    session: AsyncSession,
    event_type: PageEvent,
    space: PageSpace,
    actor_id: uuid.UUID,
    payload: dict,
    diff: list[dict] | None = None,
) -> None:
    await events.emit(
        session,
        event_type=event_type,
        entity_type=PageEntity.SPACE,
        entity_id=space.id,
        actor_id=actor_id,
        payload=payload,
        changes=diff,
    )


async def find_space_by_external(
    session: AsyncSession, external_source: str, external_id: str
) -> PageSpace | None:
    """The space a previous import made from that foreign space (spec 117) — so
    re-importing lands in the space it made rather than creating "Space PIP (2)"."""
    if not external_id:
        return None
    return await session.scalar(
        select(PageSpace).where(
            PageSpace.external_source == external_source,
            PageSpace.external_id == external_id,
        )
    )


async def create_space(
    session: AsyncSession,
    data: PageSpaceCreate,
    actor_id: uuid.UUID,
    *,
    permissions: "frozenset" = frozenset(),
) -> PageSpace:
    slug = data.slug or core.slugify(data.name)
    if await _slug_clash(session, slug):
        raise ConflictError(PageEntity.SPACE, slug)
    from .service import _may_import  # deferred: service imports spaces

    importing = _may_import(permissions)
    space = PageSpace(
        name=data.name,
        slug=slug,
        description=data.description,
        position=data.position,
        external_source=data.external_source if importing else "",
        external_id=data.external_id if importing else "",
    )
    session.add(space)
    await session.flush()
    await _emit_space(
        session, PageEvent.SPACE_CREATED, space, actor_id,
        {"name": space.name, "slug": space.slug},
    )
    return space


async def update_space(
    session: AsyncSession, space_id: uuid.UUID, data: PageSpaceUpdate, actor_id: uuid.UUID
) -> PageSpace:
    space = await get_space(session, space_id)
    changed: list[str] = []
    diff: list[dict] = []
    for field in ("name", "slug", "description", "position"):
        value = getattr(data, field)
        if value is not None and value != getattr(space, field):
            if field == "slug" and await _slug_clash(
                session, value, exclude=space.id
            ):
                raise ConflictError(PageEntity.SPACE, value)
            diff.append({"field": field, "from": getattr(space, field), "to": value})
            setattr(space, field, value)
            changed.append(field)
    await session.flush()
    if changed:
        await _emit_space(
            session, PageEvent.SPACE_UPDATED, space, actor_id,
            {"name": space.name, "changed": changed},
            diff,
        )
    return space


async def delete_space(
    session: AsyncSession, space_id: uuid.UUID, *, force: bool, actor_id: uuid.UUID
) -> None:
    space = await get_space(session, space_id)
    count = await session.scalar(
        select(func.count()).select_from(Page).where(Page.space_id == space_id)
    )
    if count and not force:
        raise ConflictError(
            PageEntity.SPACE,
            reason=f"space has {count} page(s) — delete them or pass force=true",
        )
    await session.delete(space)  # pages/versions/links go via FK CASCADE
    await session.flush()
    await _emit_space(
        session, PageEvent.SPACE_DELETED, space, actor_id,
        {"name": space.name, "page_count": count or 0},
    )


async def list_spaces(session: AsyncSession) -> list[PageSpaceRead]:
    result = await session.execute(
        select(PageSpace).order_by(PageSpace.position, PageSpace.name, PageSpace.id)
    )
    spaces = list(result.scalars())
    return await read_spaces(session, spaces)


async def read_spaces(
    session: AsyncSession, spaces: list[PageSpace]
) -> list[PageSpaceRead]:
    """Hydrate the existing live-page count contract for a selected window."""
    counts: dict[uuid.UUID, int] = dict(
        (
            await session.execute(
                select(Page.space_id, func.count())
                .where(
                    Page.space_id.in_([s.id for s in spaces]),
                    Page.archived_at.is_(None),
                )
                .group_by(Page.space_id)
            )
        ).all()
    ) if spaces else {}
    # Spec 121 (RADD-1147): `public` is the Public → Anyone grant on the space.
    from radd.modules.auth import public_access  # deferred: auth loads after pages' models

    public = await public_access.spaces_public(session, [s.id for s in spaces])
    return [
        PageSpaceRead.model_validate(space).model_copy(
            update={"page_count": counts.get(space.id, 0), "public": public.get(space.id, False)}
        )
        for space in spaces
    ]
