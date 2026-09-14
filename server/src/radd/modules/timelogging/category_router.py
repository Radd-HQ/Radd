"""Work-category CRUD (globally-configurable, like labels/states)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser

from . import categories
from .models import WorkCategory
from .schemas import WorkCategoryCreate, WorkCategoryRead, WorkCategoryUpdate

router = APIRouter(prefix="/work-categories", tags=["timelogging"])

Session = Annotated[AsyncSession, Depends(get_session)]


def _read(category: WorkCategory) -> WorkCategoryRead:
    return WorkCategoryRead(
        id=category.id,
        name=category.name,
        position=category.position,
        archived=category.archived,
    )


@router.get("", response_model=list[WorkCategoryRead])
async def list_categories(
    session: Session,
    user: CurrentUser,
    include_archived: Annotated[bool, Query()] = False,
) -> list[WorkCategoryRead]:
    # Member floor (RADD-788): item.read in SOME project, not the global atom.
    if not await authz.readable_projects(session, user):
        return []
    cats = await categories.list_categories(session, include_archived=include_archived)
    return [_read(c) for c in cats]


@router.post("", response_model=WorkCategoryRead, status_code=201)
async def create_category(
    data: WorkCategoryCreate, session: Session, user: CurrentUser
) -> WorkCategoryRead:
    await authz.require(session, user, authz.Permission.GLOBAL_MANAGE)
    return _read(await categories.create_category(session, data, actor_id=user.id))


@router.patch("/{category_id}", response_model=WorkCategoryRead)
async def update_category(
    category_id: uuid.UUID, data: WorkCategoryUpdate, session: Session, user: CurrentUser
) -> WorkCategoryRead:
    await categories.get_category(session, category_id)  # 404 before the 403
    await authz.require(session, user, authz.Permission.GLOBAL_MANAGE)
    return _read(
        await categories.update_category(session, category_id, data, actor_id=user.id)
    )
