"""Doc-space CRUD (spec 43). Pages/versions live in service.py."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, NotFoundError
from radd.modules.events import service as events

from . import core
from .models import DocPage, DocSpace
from .schemas import DocSpaceCreate, DocSpaceRead, DocSpaceUpdate
from .types import DocEntity, DocEvent


async def get_space(session: AsyncSession, space_id: uuid.UUID) -> DocSpace:
    space = await session.get(DocSpace, space_id)
    if space is None:
        raise NotFoundError(DocEntity.SPACE, space_id)
    return space


async def _slug_clash(
    session: AsyncSession, slug: str, exclude: uuid.UUID | None = None
) -> bool:
    stmt = select(DocSpace.id).where(DocSpace.slug == slug)
    if exclude is not None:
        stmt = stmt.where(DocSpace.id != exclude)
    return (await session.scalar(stmt)) is not None


async def _emit_space(
    session: AsyncSession,
    event_type: DocEvent,
    space: DocSpace,
    actor_id: uuid.UUID,
    payload: dict,
) -> None:
    await events.emit(
        session,
        event_type=event_type,
        entity_type=DocEntity.SPACE,
        entity_id=space.id,
        actor_id=actor_id,
        payload=payload,
    )


async def create_space(
    session: AsyncSession, data: DocSpaceCreate, actor_id: uuid.UUID
) -> DocSpace:
    slug = data.slug or core.slugify(data.name)
    if await _slug_clash(session, slug):
        raise ConflictError(DocEntity.SPACE, slug)
    space = DocSpace(
        name=data.name,
        slug=slug,
        description=data.description,
        position=data.position,
    )
    session.add(space)
    await session.flush()
    await _emit_space(
        session, DocEvent.SPACE_CREATED, space, actor_id,
        {"name": space.name, "slug": space.slug},
    )
    return space


async def update_space(
    session: AsyncSession, space_id: uuid.UUID, data: DocSpaceUpdate, actor_id: uuid.UUID
) -> DocSpace:
    space = await get_space(session, space_id)
    changed: list[str] = []
    for field in ("name", "slug", "description", "position", "public"):
        value = getattr(data, field)
        if value is not None and value != getattr(space, field):
            if field == "slug" and await _slug_clash(
                session, value, exclude=space.id
            ):
                raise ConflictError(DocEntity.SPACE, value)
            setattr(space, field, value)
            changed.append(field)
    await session.flush()
    if changed:
        await _emit_space(
            session, DocEvent.SPACE_UPDATED, space, actor_id,
            {"name": space.name, "changed": changed},
        )
    return space


async def delete_space(
    session: AsyncSession, space_id: uuid.UUID, *, force: bool, actor_id: uuid.UUID
) -> None:
    space = await get_space(session, space_id)
    count = await session.scalar(
        select(func.count()).select_from(DocPage).where(DocPage.space_id == space_id)
    )
    if count and not force:
        raise ConflictError(
            DocEntity.SPACE,
            reason=f"space has {count} page(s) — delete them or pass force=true",
        )
    await session.delete(space)  # pages/versions/links go via FK CASCADE
    await session.flush()
    await _emit_space(
        session, DocEvent.SPACE_DELETED, space, actor_id,
        {"name": space.name, "page_count": count or 0},
    )


async def list_spaces(session: AsyncSession) -> list[DocSpaceRead]:
    result = await session.execute(
        select(DocSpace).order_by(DocSpace.position, DocSpace.name)
    )
    spaces = list(result.scalars())
    counts: dict[uuid.UUID, int] = dict(
        (
            await session.execute(
                select(DocPage.space_id, func.count())
                .where(
                    DocPage.space_id.in_([s.id for s in spaces]),
                    DocPage.archived_at.is_(None),
                )
                .group_by(DocPage.space_id)
            )
        ).all()
    ) if spaces else {}
    return [
        DocSpaceRead.model_validate(space).model_copy(
            update={"page_count": counts.get(space.id, 0)}
        )
        for space in spaces
    ]
