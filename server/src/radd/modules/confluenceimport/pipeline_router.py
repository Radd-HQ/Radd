"""Snapshots, plans, runs and rollback — HTTP (spec 117).

Instance-admin only, as `router.py` explains. Literal segments are declared before
any `/{id}` route that could swallow them (RADD-761).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.exceptions import ForbiddenError
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser
from radd.modules.auth.models import User

from . import plan as plan_service, rollback, runs
from .schemas import (
    PlanCreate,
    PlanProblem,
    PlanRead,
    PlanUpdate,
    RollbackPreflight,
    RunRead,
    RunStart,
    SnapshotCreate,
    SnapshotRead,
)
from .snapshot import download, service as snapshot_service

pipeline_router = APIRouter(prefix="/confluence", tags=["confluence import"])

Session = Annotated[AsyncSession, Depends(get_session)]


def _admin(actor: User) -> None:
    if not authz.is_instance_admin(actor):
        raise ForbiddenError("Confluence import requires an instance admin")


# --- snapshots ----------------------------------------------------------------


@pipeline_router.get("/snapshots", response_model=list[SnapshotRead])
async def list_snapshots(session: Session, user: CurrentUser) -> list[SnapshotRead]:
    _admin(user)
    return [SnapshotRead.model_validate(s) for s in await download.list_snapshots(session)]


@pipeline_router.post("/snapshots", response_model=SnapshotRead, status_code=201)
async def create_snapshot(
    data: SnapshotCreate, session: Session, user: CurrentUser
) -> SnapshotRead:
    """Fire and forget — the row carries the progress from here."""
    _admin(user)
    snapshot = await snapshot_service.create_snapshot(session, data, user.id)
    await session.commit()
    download.start(snapshot.id)
    return SnapshotRead.model_validate(snapshot)


@pipeline_router.get("/snapshots/{snapshot_id}", response_model=SnapshotRead)
async def get_snapshot(
    snapshot_id: uuid.UUID, session: Session, user: CurrentUser
) -> SnapshotRead:
    _admin(user)
    return SnapshotRead.model_validate(
        await snapshot_service.get_snapshot(session, snapshot_id)
    )


@pipeline_router.post("/snapshots/{snapshot_id}/cancel", response_model=SnapshotRead)
async def cancel_snapshot(
    snapshot_id: uuid.UUID, session: Session, user: CurrentUser
) -> SnapshotRead:
    _admin(user)
    snapshot = await snapshot_service.request_cancel(session, snapshot_id)
    await session.commit()
    return SnapshotRead.model_validate(snapshot)


@pipeline_router.delete("/snapshots/{snapshot_id}", status_code=204)
async def delete_snapshot(
    snapshot_id: uuid.UUID, session: Session, user: CurrentUser
) -> None:
    _admin(user)
    await snapshot_service.delete_snapshot(session, snapshot_id)
    await session.commit()


# --- plans --------------------------------------------------------------------


@pipeline_router.get("/plans", response_model=list[PlanRead])
async def list_plans(session: Session, user: CurrentUser) -> list[PlanRead]:
    _admin(user)
    return [PlanRead.model_validate(p) for p in await plan_service.list_plans(session)]


@pipeline_router.post("/plans", response_model=PlanRead, status_code=201)
async def create_plan(data: PlanCreate, session: Session, user: CurrentUser) -> PlanRead:
    """Pre-filled by profiling the cache — including the macro census."""
    _admin(user)
    plan = await plan_service.create_plan(session, data)
    await session.commit()
    return PlanRead.model_validate(plan)


@pipeline_router.get("/plans/{plan_id}", response_model=PlanRead)
async def get_plan(plan_id: uuid.UUID, session: Session, user: CurrentUser) -> PlanRead:
    _admin(user)
    return PlanRead.model_validate(await plan_service.get_plan(session, plan_id))


@pipeline_router.patch("/plans/{plan_id}", response_model=PlanRead)
async def update_plan(
    plan_id: uuid.UUID, data: PlanUpdate, session: Session, user: CurrentUser
) -> PlanRead:
    _admin(user)
    plan = await plan_service.update_plan(session, plan_id, data)
    await session.commit()
    return PlanRead.model_validate(plan)


@pipeline_router.delete("/plans/{plan_id}", status_code=204)
async def delete_plan(plan_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    _admin(user)
    await plan_service.delete_plan(session, plan_id)
    await session.commit()


@pipeline_router.post("/plans/{plan_id}/validate", response_model=list[PlanProblem])
async def validate_plan(
    plan_id: uuid.UUID, session: Session, user: CurrentUser
) -> list[PlanProblem]:
    _admin(user)
    return await plan_service.validate_plan(session, plan_id)


# --- runs ---------------------------------------------------------------------


@pipeline_router.get("/runs", response_model=list[RunRead])
async def list_runs(session: Session, user: CurrentUser) -> list[RunRead]:
    _admin(user)
    return [RunRead.model_validate(r) for r in await runs.list_runs(session)]


@pipeline_router.post("/runs", response_model=RunRead, status_code=201)
async def start_run(data: RunStart, session: Session, user: CurrentUser) -> RunRead:
    """A dry run is always allowed; a real one refuses while the plan has
    problems, because every one of them changes what would be written."""
    _admin(user)
    run = await runs.start_run(session, data.plan_id, dry_run=data.dry_run, actor_id=user.id)
    await session.commit()
    runs.start(run.id)
    return RunRead.model_validate(run)


@pipeline_router.get("/runs/{run_id}", response_model=RunRead)
async def get_run(run_id: uuid.UUID, session: Session, user: CurrentUser) -> RunRead:
    _admin(user)
    return RunRead.model_validate(await runs.get_run(session, run_id))


@pipeline_router.post("/runs/{run_id}/cancel", response_model=RunRead)
async def cancel_run(run_id: uuid.UUID, session: Session, user: CurrentUser) -> RunRead:
    _admin(user)
    run = await runs.request_cancel(session, run_id)
    await session.commit()
    return RunRead.model_validate(run)


@pipeline_router.get("/runs/{run_id}/rollback", response_model=RollbackPreflight)
async def rollback_preflight(
    run_id: uuid.UUID, session: Session, user: CurrentUser
) -> RollbackPreflight:
    _admin(user)
    return await rollback.preflight(session, await runs.get_run(session, run_id))


@pipeline_router.post("/runs/{run_id}/rollback")
async def rollback_run(
    run_id: uuid.UUID,
    session: Session,
    user: CurrentUser,
    include_containers: bool = False,
    skip_edited: bool = True,
) -> dict:
    _admin(user)
    return await rollback.execute(
        session,
        await runs.get_run(session, run_id),
        include_containers=include_containers,
        skip_edited=skip_edited,
    )
