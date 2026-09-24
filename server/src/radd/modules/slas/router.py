import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.auth import authz
from radd.modules.auth.authz import Permission
from radd.modules.auth.deps import CurrentUser
from radd.modules.items import service as items_service
from radd.modules.projects import service as projects_service

from . import evaluation, service
from .queue import queue_items
from radd.modules.items.schemas import ItemRead
from .schemas import (
    BatchTimerRead,
    ItemSlaEntry,
    ItemSlaRead,
    PolicyCreate,
    PolicyRead,
    PolicyUpdate,
    SlaBatchRequest,
    TimerRead,
)

router = APIRouter(tags=["slas"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/sla-policies", response_model=list[PolicyRead])
async def list_policies(
    project_id: uuid.UUID, session: Session, user: CurrentUser
) -> list[PolicyRead]:
    """One project's policies (spec 67: SLA policies are project-level)."""
    project = await projects_service.get_project(session, project_id)
    await authz.require(session, user, Permission.ITEM_READ, project=project)
    return [
        PolicyRead.model_validate(policy)
        for policy in await service.list_policies(session, project_id)
    ]


@router.post("/sla-policies", response_model=PolicyRead, status_code=201)
async def create_policy(data: PolicyCreate, session: Session, user: CurrentUser) -> PolicyRead:
    # RADD-1303: checked against the policy's OWN project — a project's
    # Manager manages its SLAs, and no one else's.
    project = await projects_service.get_project(session, data.project_id)
    await authz.require(session, user, Permission.SLA_CREATE, project=project)
    return PolicyRead.model_validate(await service.create_policy(session, data, actor_id=user.id))


@router.patch("/sla-policies/{policy_id}", response_model=PolicyRead)
async def update_policy(
    policy_id: uuid.UUID, data: PolicyUpdate, session: Session, user: CurrentUser
) -> PolicyRead:
    policy = await service.get_policy(session, policy_id)
    project = await projects_service.get_project(session, policy.project_id)
    await authz.require(session, user, Permission.SLA_UPDATE, project=project)
    return PolicyRead.model_validate(
        await service.update_policy(session, policy_id, data, actor_id=user.id)
    )


@router.delete("/sla-policies/{policy_id}", status_code=204)
async def delete_policy(policy_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    policy = await service.get_policy(session, policy_id)
    project = await projects_service.get_project(session, policy.project_id)
    await authz.require(session, user, Permission.SLA_DELETE, project=project)
    await service.delete_policy(session, policy_id, actor_id=user.id)


@router.post("/items/sla/batch", response_model=dict[uuid.UUID, list[BatchTimerRead]])
async def item_sla_batch(
    data: SlaBatchRequest, session: Session, user: CurrentUser
) -> dict[uuid.UUID, list[BatchTimerRead]]:
    """Live timers for a page of list/board items (spec 63): the request is
    filtered to items the actor can read; each item is computed under its
    MATCHED policy (first-match). Items without a policy are omitted."""
    return await evaluation.batch_sla(session, user, data.item_ids)


@router.get("/items/{item_id}/sla", response_model=ItemSlaRead)
async def item_sla(item_id: uuid.UUID, session: Session, user: CurrentUser) -> ItemSlaRead:
    """Live timer status under the item's MATCHED policy (spec 63 first-match;
    display always recomputes — the engine's stored rows only gate breach-event
    dedup). At most one entry; an empty list = no policy applies."""
    item, _project, _perms = await items_service.require_readable_item(session, item_id, user)
    entries: list[ItemSlaEntry] = []
    policy = await service.matched_policy(session, item)
    if policy is not None:
        evaluated = await evaluation.evaluate_items(session, policy, [item_id])
        timers_read = [
            TimerRead(
                kind=kind,
                target_minutes=target,
                due_at=status.due_at,
                met_at=status.met_at,
                breached=status.breached,
                paused=status.paused,
                remaining_seconds=status.remaining_seconds,
            )
            for kind, (target, status) in evaluated.get(item_id, {}).items()
        ]
        if timers_read:
            entries.append(
                ItemSlaEntry(policy_id=policy.id, policy_name=policy.name, timers=timers_read)
            )
    return ItemSlaRead(entries=entries)


@router.get("/sla-queue-items", response_model=list[ItemRead])
async def queue_page(session: Session, user: CurrentUser, project_id: uuid.UUID | None = None,
                     q: str = "", limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    return await queue_items(session, user, project_id=project_id, q=q, limit=limit, offset=offset)
