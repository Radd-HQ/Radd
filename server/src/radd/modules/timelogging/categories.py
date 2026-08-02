"""Work categories: globally-configurable tags for a worklog.

Default categories seed via an idempotent on-startup ensure (spec 86 stage 3 —
replaces the retired `workspace.created` hook; the seed script calls
`ensure_default_categories` directly)."""

import uuid
from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import SessionLocal
from radd.exceptions import ConflictError, NotFoundError

from .models import WorkCategory
from .schemas import WorkCategoryCreate, WorkCategoryUpdate
from .types import DEFAULT_WORK_CATEGORIES, TimelogEntity


async def list_categories(
    session: AsyncSession, *, include_archived: bool = False
) -> list[WorkCategory]:
    query = select(WorkCategory)
    if not include_archived:
        query = query.where(WorkCategory.archived.is_(False))
    query = query.order_by(WorkCategory.position, WorkCategory.name)
    return list((await session.execute(query)).scalars())


async def get_category(session: AsyncSession, category_id: uuid.UUID) -> WorkCategory:
    category = await session.get(WorkCategory, category_id)
    if category is None:
        raise NotFoundError(TimelogEntity.WORK_CATEGORY, category_id)
    return category


async def categories_by_ids(
    session: AsyncSession, ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, WorkCategory]:
    clean = {cid for cid in ids if cid is not None}
    if not clean:
        return {}
    result = await session.execute(select(WorkCategory).where(WorkCategory.id.in_(clean)))
    return {c.id: c for c in result.scalars()}


async def resolve_category(session: AsyncSession, category_id: uuid.UUID) -> WorkCategory:
    """Fetch a category (categories are global — 404 if it doesn't exist)."""
    return await get_category(session, category_id)


async def create_category(
    session: AsyncSession, data: WorkCategoryCreate
) -> WorkCategory:
    existing = await session.scalar(
        select(WorkCategory.id).where(WorkCategory.name == data.name)
    )
    if existing:
        raise ConflictError(TimelogEntity.WORK_CATEGORY, data.name)
    next_position = (
        await session.scalar(
            select(func.coalesce(func.max(WorkCategory.position), -1) + 1)
        )
    ) or 0
    category = WorkCategory(name=data.name, position=next_position)
    session.add(category)
    await session.flush()
    return category


async def update_category(
    session: AsyncSession, category_id: uuid.UUID, data: WorkCategoryUpdate
) -> WorkCategory:
    category = await get_category(session, category_id)
    if data.name is not None and data.name != category.name:
        clash = await session.scalar(
            select(WorkCategory.id).where(
                WorkCategory.name == data.name,
                WorkCategory.id != category_id,
            )
        )
        if clash:
            raise ConflictError(TimelogEntity.WORK_CATEGORY, data.name)
        category.name = data.name
    if data.archived is not None:
        category.archived = data.archived
    await session.flush()
    return category


async def ensure_default_categories(session: AsyncSession) -> None:
    """Idempotently seed the default global work categories (startup + seed reuse this)."""
    existing = set(
        (await session.execute(select(WorkCategory.name))).scalars()
    )
    for position, name in enumerate(DEFAULT_WORK_CATEGORIES):
        if name in existing:
            continue
        session.add(WorkCategory(name=name, position=position))
    await session.flush()


async def ensure_seeded() -> None:
    """On-startup ensure: the default global work categories exist (spec 86 stage 3
    — replaces the retired `workspace.created` seed hook)."""
    async with SessionLocal() as session:
        await ensure_default_categories(session)
        await session.commit()
