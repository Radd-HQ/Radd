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


async def _item_project(session: AsyncSession, item_id: uuid.UUID):
    item = await items_service.require_item(session, item_id)
    project = await projects_service.get_project(session, item.project_id)
    return item, project


@router.post("/items/{item_id}/worklogs", response_model=WorklogRead, status_code=201)
async def log_work(
    item_id: uuid.UUID, data: WorklogCreate, session: Session, user: CurrentUser
) -> WorklogRead:
    _, project = await _item_project(session, item_id)
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
    _, project = await _item_project(session, item_id)
    await authz.require(session, user, authz.Permission.ITEM_READ, project=project)
    return await service.item_summary(session, item_id, project)


@router.put("/items/{item_id}/estimate", response_model=ItemTimeSummary)
async def set_estimate(
    item_id: uuid.UUID, data: EstimateSet, session: Session, user: CurrentUser
) -> ItemTimeSummary:
    _, project = await _item_project(session, item_id)
    await authz.require(session, user, authz.Permission.ITEM_UPDATE, project=project)
    await enablement.require_enabled(session, project.id)
    await service.set_estimate(session, item_id, data)
    return await service.item_summary(session, item_id, project)


@router.delete("/items/{item_id}/estimate", response_model=ItemTimeSummary)
async def clear_estimate(
    item_id: uuid.UUID, session: Session, user: CurrentUser
) -> ItemTimeSummary:
    _, project = await _item_project(session, item_id)
    await authz.require(session, user, authz.Permission.ITEM_UPDATE, project=project)
    await service.clear_estimate(session, item_id)
    return await service.item_summary(session, item_id, project)


async def _can_log_general(session: AsyncSession, user) -> bool:
    """May log itemless general time: holds worklog.write on ≥1 project (spec 59
    — mirrors the settings-nav any-project gate)."""
    projects = await projects_service.list_projects(session)
    perms_by_project = await authz.permissions_for_projects(session, user, projects)
    return any(
        authz.Permission.WORKLOG_WRITE in perms for perms in perms_by_project.values()
    )


@router.post("/worklogs", response_model=WorklogRead, status_code=201)
async def log_general_work(
    data: GeneralWorklogCreate, session: Session, user: CurrentUser
) -> WorklogRead:
    """Itemless time (spec 59): meetings/admin/general — category required, anchored
    to an optional project."""
    if data.project_id is not None:
        project = await projects_service.get_project(session, data.project_id)
        await authz.require(session, user, authz.Permission.WORKLOG_WRITE, project=project)
    elif not await _can_log_general(session, user):
        raise ForbiddenError("logging general time needs worklog.write on some project")
    return await service.create_general_worklog(session, data, user.id, today=date.today())


async def _authorize_mutation(
    session: AsyncSession, user, worklog, *, others: authz.Permission
) -> None:
    """Author (with worklog.write) or a holder of `others` may edit/delete a worklog
    (spec 50: worklog.delete for deletion, project.manage for editing another's).
    Spec 59: itemless entries — the author needs the general-log gate; others need
    `others` at global scope (admins)."""
    project = await service.worklog_scope(session, worklog)
    is_author = worklog.author_id == user.id
    if project is not None:
        perms = await authz.effective_permissions(session, user, project=project)
        if (is_author and authz.Permission.WORKLOG_WRITE in perms) or (others in perms):
            return
    else:
        if is_author and await _can_log_general(session, user):
            return
        perms = await authz.effective_permissions(session, user)
        if others in perms:
            return
    raise ForbiddenError("only the worklog's author or a project manager may change it")


@router.patch("/worklogs/{worklog_id}", response_model=WorklogRead)
async def update_worklog(
    worklog_id: uuid.UUID, data: WorklogUpdate, session: Session, user: CurrentUser
) -> WorklogRead:
    worklog = await service.get_worklog(session, worklog_id)
    await _authorize_mutation(session, user, worklog, others=authz.Permission.PROJECT_MANAGE)
    return await service.update_worklog(session, worklog, data, user.id)


@router.delete("/worklogs/{worklog_id}", status_code=204)
async def delete_worklog(
    worklog_id: uuid.UUID, session: Session, user: CurrentUser
) -> None:
    worklog = await service.get_worklog(session, worklog_id)
    await _authorize_mutation(session, user, worklog, others=authz.Permission.WORKLOG_DELETE)
    await service.delete_worklog(session, worklog, user.id)
