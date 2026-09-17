"""Item-scoped worklogs + estimate, and worklog-scoped edit/delete."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.exceptions import ForbiddenError
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser
from radd.modules.items import service as items_service
from radd.modules.projects import service as projects_service

from . import enablement, service
from .schemas import (
    EstimateSet,
    GeneralWorklogCreate,
    ItemTimeBatchEntry,
    ItemTimeSummary,
    TimelogBatchRequest,
    WorklogCreate,
    WorklogRead,
    WorklogUpdate,
)

router = APIRouter(tags=["timelogging"])

Session = Annotated[AsyncSession, Depends(get_session)]


async def _item_project(session: AsyncSession, item_id: uuid.UUID, user):
    # RADD-823: THE item seam — worklog surfaces inherit per-item read rules;
    # write atoms (worklog.write, item.update) layer on the same resolution.
    item, project, _perms = await items_service.require_readable_item(session, item_id, user)
    return item, project


@router.post("/items/{item_id}/worklogs", response_model=WorklogRead, status_code=201)
async def log_work(
    item_id: uuid.UUID, data: WorklogCreate, session: Session, user: CurrentUser
) -> WorklogRead:
    _, project = await _item_project(session, item_id, user)
    await authz.require(session, user, authz.Permission.WORKLOG_WRITE, project=project)
    author_id = user.id
    created_at = None
    if (data.author_id is not None and data.author_id != user.id) or data.created_at is not None:
        # Import overrides (author/timestamp): only a project manager may set them.
        perms = await authz.effective_permissions(session, user, project=project)
        if authz.Permission.PROJECT_MANAGE not in perms:
            raise ForbiddenError("only a project manager may set a worklog's author or date")
        if data.author_id is not None:
            author_id = data.author_id
        created_at = data.created_at
    return await service.create_worklog(
        session, item_id, data, author_id, today=date.today(), created_at=created_at
    )


@router.post("/items/timelog/batch", response_model=dict[uuid.UUID, ItemTimeBatchEntry])
async def item_timelog_batch(
    data: TimelogBatchRequest, session: Session, user: CurrentUser
) -> dict[uuid.UUID, ItemTimeBatchEntry]:
    """Batched estimate/logged seconds for the roadmap's auto-schedule durations
    (spec 78): filtered to items the actor can read (sla/batch idiom); readable
    ids always appear (None/0 = no estimate / nothing logged)."""
    return await service.timelog_batch(session, user, data.item_ids)


@router.get("/items/{item_id}/timelog", response_model=ItemTimeSummary)
async def item_timelog(
    item_id: uuid.UUID, session: Session, user: CurrentUser
) -> ItemTimeSummary:
    _, project = await _item_project(session, item_id, user)
    return await service.item_summary(session, item_id, project)


@router.put("/items/{item_id}/estimate", response_model=ItemTimeSummary)
async def set_estimate(
    item_id: uuid.UUID, data: EstimateSet, session: Session, user: CurrentUser
) -> ItemTimeSummary:
    item, project = await _item_project(session, item_id, user)
    permissions = await authz.require(session, user, authz.Permission.ITEM_UPDATE, project=project)
    from radd.modules.items.service.visibility import ensure_item_relation
    await ensure_item_relation(session, user, item, permissions, authz.Permission.ITEM_UPDATE)
    await enablement.require_enabled(session, project.id)
    await service.set_estimate(session, item_id, data, actor_id=user.id)
    return await service.item_summary(session, item_id, project)


@router.delete("/items/{item_id}/estimate", response_model=ItemTimeSummary)
async def clear_estimate(
    item_id: uuid.UUID, session: Session, user: CurrentUser
) -> ItemTimeSummary:
    item, project = await _item_project(session, item_id, user)
    permissions = await authz.require(session, user, authz.Permission.ITEM_UPDATE, project=project)
    from radd.modules.items.service.visibility import ensure_item_relation
    await ensure_item_relation(session, user, item, permissions, authz.Permission.ITEM_UPDATE)
    await service.clear_estimate(session, item_id, actor_id=user.id)
    return await service.item_summary(session, item_id, project)


@router.post("/worklogs", response_model=WorklogRead, status_code=201)
async def log_general_work(
    data: GeneralWorklogCreate, session: Session, user: CurrentUser
) -> WorklogRead:
    """Itemless time (spec 59): meetings/admin/general — category required, anchored
    to an optional project."""
    if data.project_id is not None:
        project = await projects_service.get_project(session, data.project_id)
        await authz.require(session, user, authz.Permission.WORKLOG_WRITE, project=project)
    elif not await service.can_log_general(session, user):
        raise ForbiddenError("logging general time needs worklog.write on some project")
    return await service.create_general_worklog(session, data, user.id, today=date.today())


@router.patch("/worklogs/{worklog_id}", response_model=WorklogRead)
async def update_worklog(
    worklog_id: uuid.UUID, data: WorklogUpdate, session: Session, user: CurrentUser
) -> WorklogRead:
    worklog = await service.get_worklog(session, worklog_id)
    await service.authorize_mutation(session, user, worklog, others=authz.Permission.PROJECT_MANAGE)
    return await service.update_worklog(session, worklog, data, user.id)


@router.delete("/worklogs/{worklog_id}", status_code=204)
async def delete_worklog(
    worklog_id: uuid.UUID, session: Session, user: CurrentUser
) -> None:
    worklog = await service.get_worklog(session, worklog_id)
    await service.authorize_mutation(session, user, worklog, others=authz.Permission.WORKLOG_DELETE)
    await service.delete_worklog(session, worklog, user.id)
