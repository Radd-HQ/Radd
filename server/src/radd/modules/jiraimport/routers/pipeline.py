"""Plans, dry runs, imports, relink and rollback (spec 100).

The pipeline the wizard walks: create a plan from a cached snapshot, edit its
mapping tables, provision the real targets, dry-run against them, import, and —
if the result is wrong — roll the whole thing back.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.exceptions import ConflictError, ForbiddenError, NotFoundError
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser
from radd.modules.auth.models import User

from .. import relink, rollback as rollback_mod, runs
from ..models import JiraRun
from ..plan import service as plan_service
from ..plan.schemas import (
    PlanCreate,
    PlanRead,
    PlanUpdate,
    PlanValidation,
)
from ..types import JiraEntity, RunKind, RunStage
from .schemas import (
    PendingSummary,
    RollbackPreflight,
    RollbackStart,
    RunRead,
    RunStart,
)

router = APIRouter(prefix="/jira", tags=["jira import"])

Session = Annotated[AsyncSession, Depends(get_session)]


def _admin(actor: User) -> None:
    if not authz.is_instance_admin(actor):
        raise ForbiddenError("Jira import requires an instance admin")


# --- plans --------------------------------------------------------------------


@router.get("/plans", response_model=list[PlanRead])
async def list_plans(session: Session, user: CurrentUser) -> list[PlanRead]:
    _admin(user)
    return [PlanRead.model_validate(p) for p in await plan_service.list_plans(session)]


@router.post("/plans", response_model=PlanRead, status_code=201)
async def create_plan(data: PlanCreate, session: Session, user: CurrentUser) -> PlanRead:
    """A new plan, PRE-FILLED by profiling the snapshot — so the mapping tables
    open on suggestions for every field and every vocabulary value, not a blank
    sheet of 337 fields and 83 statuses."""
    _admin(user)
    plan = await plan_service.create_plan(session, data)
    await session.commit()
    return PlanRead.model_validate(plan)


@router.get("/plans/{plan_id}", response_model=PlanRead)
async def get_plan(plan_id: uuid.UUID, session: Session, user: CurrentUser) -> PlanRead:
    _admin(user)
    return PlanRead.model_validate(await plan_service.get_plan(session, plan_id))


@router.patch("/plans/{plan_id}", response_model=PlanRead)
async def update_plan(
    plan_id: uuid.UUID, data: PlanUpdate, session: Session, user: CurrentUser
) -> PlanRead:
    _admin(user)
    plan = await plan_service.update_plan(session, plan_id, data)
    await session.commit()
    return PlanRead.model_validate(plan)


@router.delete("/plans/{plan_id}", status_code=204)
async def delete_plan(plan_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    _admin(user)
    await plan_service.delete_plan(session, plan_id)
    await session.commit()


@router.post("/plans/{plan_id}/validate", response_model=PlanValidation)
async def validate_plan(
    plan_id: uuid.UUID, session: Session, user: CurrentUser
) -> PlanValidation:
    _admin(user)
    plan = await plan_service.get_plan(session, plan_id)
    problems = await plan_service.validate_plan(session, plan)
    return PlanValidation(ok=not problems, problems=problems)


# --- runs ---------------------------------------------------------------------


@router.post("/runs", response_model=RunRead, status_code=201)
async def start_run(data: RunStart, session: Session, user: CurrentUser) -> RunRead:
    """Start a dry run or a real import. Returns immediately; poll for progress.

    A dry run resolves everything and writes NOTHING — same code path as the
    import, so it cannot disagree with what the import will do.
    """
    _admin(user)
    plan = await plan_service.get_plan(session, data.plan_id)
    problems = await plan_service.validate_plan(session, plan)
    if problems and data.kind is RunKind.IMPORT:
        raise ConflictError(
            JiraEntity.IMPORT_PLAN,
            reason=f"{len(problems)} mapping problem(s) — fix them or run a dry run first",
        )
    run = JiraRun(
        plan_id=plan.id,
        snapshot_id=plan.snapshot_id,
        actor_id=user.id,
        kind=data.kind.value,
        dry_run=data.kind is RunKind.DRY_RUN,
        plan_snapshot={
            "name": plan.name,
            "radd_project_key": plan.radd_project_key,
            "radd_project_name": plan.radd_project_name,
            "mappings": plan.mappings,
            "options": plan.options,
        },
    )
    session.add(run)
    await session.commit()
    runs.start(run.id)
    return RunRead.model_validate(run)


@router.get("/runs", response_model=list[RunRead])
async def list_runs(session: Session, user: CurrentUser) -> list[RunRead]:
    _admin(user)
    from sqlalchemy import select

    result = await session.execute(select(JiraRun).order_by(JiraRun.created_at.desc()).limit(50))
    return [RunRead.model_validate(r) for r in result.scalars()]


@router.get("/runs/{run_id}", response_model=RunRead)
async def get_run(run_id: uuid.UUID, session: Session, user: CurrentUser) -> RunRead:
    _admin(user)
    return RunRead.model_validate(await _require_run(session, run_id))


@router.post("/runs/{run_id}/cancel", response_model=RunRead)
async def cancel_run(run_id: uuid.UUID, session: Session, user: CurrentUser) -> RunRead:
    """Stop cooperatively — the pipeline halts between issues, keeping everything
    already written (and still rollback-able)."""
    _admin(user)
    run = await _require_run(session, run_id)
    if RunStage(run.stage) not in (RunStage.DONE, RunStage.FAILED):
        run.stage = RunStage.CANCELED.value
        await session.commit()
    return RunRead.model_validate(run)


# --- rollback -----------------------------------------------------------------


@router.get("/runs/{run_id}/rollback", response_model=RollbackPreflight)
async def rollback_preflight(
    run_id: uuid.UUID, session: Session, user: CurrentUser
) -> RollbackPreflight:
    """What undoing this run would touch — including anything a human has edited
    since, so destroying their work is a choice rather than a surprise."""
    _admin(user)
    run = await _require_run(session, run_id)
    result = await rollback_mod.preflight(session, run)
    return RollbackPreflight(
        total=result.total, by_entity=result.by_entity, edited_since=result.edited_since
    )


@router.post("/runs/{run_id}/rollback", response_model=RunRead)
async def do_rollback(
    run_id: uuid.UUID, data: RollbackStart, session: Session, user: CurrentUser
) -> RunRead:
    """Undo the run. `include_schema=false` keeps the project and its fields, so a
    mapping can be corrected and re-imported without provisioning again."""
    _admin(user)
    run = await _require_run(session, run_id)
    result = await rollback_mod.execute(
        session, run, include_schema=data.include_schema, skip_edited=data.skip_edited
    )
    run.counts = {
        **(run.counts or {}),
        "rolled_back": result.undone,
        "restored": result.restored,
        "rollback_skipped": result.skipped,
    }
    run.problems = [*(run.problems or []), *[p.as_dict() for p in result.problems]]
    await session.commit()
    return RunRead.model_validate(run)


# --- relink -------------------------------------------------------------------


@router.get("/pending", response_model=PendingSummary)
async def pending(session: Session, user: CurrentUser) -> PendingSummary:
    """Cross-project references still waiting for their target to be imported."""
    _admin(user)
    by_project = await relink.pending_summary(session)
    return PendingSummary(total=sum(by_project.values()), by_project=by_project)


@router.post("/relink", response_model=PendingSummary)
async def do_relink(session: Session, user: CurrentUser) -> PendingSummary:
    """Retry every pending reference against the current database.

    Repeatable and cross-run by design: a reference recorded while importing DEV
    is resolved by the import of TD, whenever that happens.
    """
    _admin(user)
    result = await relink.resolve_all(session, user)
    await session.commit()
    return PendingSummary(
        total=result.still_pending,
        by_project=result.pending_by_project,
        resolved=result.resolved,
    )


async def _require_run(session: AsyncSession, run_id: uuid.UUID) -> JiraRun:
    run = await session.get(JiraRun, run_id)
    if run is None:
        raise NotFoundError(JiraEntity.IMPORT_RUN, run_id)
    return run
