"""SLA policy CRUD + first-match resolution (specs 30/63/67).

Spec 63 retired spec 30's "every enabled policy applies": policies are ordered
by (position, created_at) and ONE policy — the first whose filters match —
governs an item. The filters are priority (spec 63) and issue type (RADD-1043).
Spec 67 made policies project-level: an item is only
ever matched against its own project's policies (no workspace-wide policies).
Timer evaluation lives in `evaluation.py`.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import ConflictError, NotFoundError
from radd.modules.events import service as events
from radd.modules.items.models import WorkItem
from radd.modules.projects import service as projects_service

from .models import SlaPolicy
from .schemas import PolicyCreate, PolicyUpdate
from .types import SlaEntity, SlaEvent


# --- policy CRUD ---


def _validate_business_window(start: int | None, end: int | None) -> None:
    """Spec 63: minutes-from-midnight pair — both-or-neither, start < end."""
    if (start is None) != (end is None):
        raise ConflictError(SlaEntity.POLICY, reason="business hours need both start and end")
    if start is not None and end is not None and start >= end:
        raise ConflictError(SlaEntity.POLICY, reason="business hours must start before they end")


async def _emit_policy(
    session: AsyncSession, event_type: SlaEvent, policy: SlaPolicy, actor_id: uuid.UUID
) -> None:
    await events.emit(
        session,
        event_type=event_type,
        entity_type=SlaEntity.POLICY,
        entity_id=policy.id,
        actor_id=actor_id,
        payload={"name": policy.name, "enabled": policy.enabled},
    )


async def create_policy(
    session: AsyncSession, data: PolicyCreate, actor_id: uuid.UUID
) -> SlaPolicy:
    # Spec 67: the project anchors the policy (validate it exists).
    await projects_service.get_project(session, data.project_id)
    _validate_business_window(data.business_start_minute, data.business_end_minute)
    policy = SlaPolicy(
        project_id=data.project_id,
        name=data.name,
        enabled=data.enabled,
        response_minutes=data.response_minutes,
        resolution_minutes=data.resolution_minutes,
        pause_state_names=data.pause_state_names,
        work_week_only=data.work_week_only,
        priorities=[priority.value for priority in data.priorities],
        issue_type_ids=[str(type_id) for type_id in data.issue_type_ids],
        position=data.position,
        business_start_minute=data.business_start_minute,
        business_end_minute=data.business_end_minute,
        warning_minutes=data.warning_minutes,
    )
    session.add(policy)
    await session.flush()
    await _emit_policy(session, SlaEvent.POLICY_CREATED, policy, actor_id)
    return policy


async def get_policy(session: AsyncSession, policy_id: uuid.UUID) -> SlaPolicy:
    policy = await session.get(SlaPolicy, policy_id)
    if policy is None:
        raise NotFoundError(SlaEntity.POLICY, policy_id)
    return policy


async def list_policies(session: AsyncSession, project_id: uuid.UUID) -> list[SlaPolicy]:
    """One project's policies in first-match order (spec 67: project-level)."""
    result = await session.execute(
        select(SlaPolicy)
        .where(SlaPolicy.project_id == project_id)
        .order_by(SlaPolicy.position, SlaPolicy.created_at)
    )
    return list(result.scalars())


async def update_policy(
    session: AsyncSession, policy_id: uuid.UUID, data: PolicyUpdate, actor_id: uuid.UUID
) -> SlaPolicy:
    policy = await get_policy(session, policy_id)
    fields_set = data.model_fields_set
    if data.name is not None:
        policy.name = data.name
    if data.enabled is not None:
        policy.enabled = data.enabled
    if "response_minutes" in fields_set:
        policy.response_minutes = data.response_minutes
    if "resolution_minutes" in fields_set:
        policy.resolution_minutes = data.resolution_minutes
    if data.pause_state_names is not None:
        policy.pause_state_names = data.pause_state_names
    if data.work_week_only is not None:
        policy.work_week_only = data.work_week_only
    if data.priorities is not None:
        policy.priorities = [priority.value for priority in data.priorities]
    if data.issue_type_ids is not None:
        policy.issue_type_ids = [str(type_id) for type_id in data.issue_type_ids]
    if data.position is not None:
        policy.position = data.position
    if "business_start_minute" in fields_set:
        policy.business_start_minute = data.business_start_minute
    if "business_end_minute" in fields_set:
        policy.business_end_minute = data.business_end_minute
    if "warning_minutes" in fields_set:
        policy.warning_minutes = data.warning_minutes
    if policy.response_minutes is None and policy.resolution_minutes is None:
        raise ConflictError(SlaEntity.POLICY, reason="a policy needs at least one target")
    _validate_business_window(policy.business_start_minute, policy.business_end_minute)
    await session.flush()
    await _emit_policy(session, SlaEvent.POLICY_UPDATED, policy, actor_id)
    return policy


async def delete_policy(
    session: AsyncSession, policy_id: uuid.UUID, actor_id: uuid.UUID
) -> None:
    policy = await get_policy(session, policy_id)
    await session.delete(policy)
    await session.flush()
    await _emit_policy(session, SlaEvent.POLICY_DELETED, policy, actor_id)


# --- first-match resolution (specs 63/67, replaces spec 30's evaluate-all) ---


def first_match(policies: Sequence[SlaPolicy], item: WorkItem) -> SlaPolicy | None:
    """The FIRST policy (pre-ordered by position, created_at) that is enabled,
    belongs to the item's project, and whose filters match the item. Pure —
    unit-tested without a database.

    Two filters, ANDed, each empty-means-any: priority (spec 63) and issue type
    (RADD-1043). An item with no type matches only a policy with no type filter
    — a filter names the types it covers, and "untyped" is not one of them.
    Ordering is untouched: the filters decide whether a policy is a candidate,
    position decides which candidate wins.
    """
    for policy in policies:
        if not policy.enabled:
            continue
        if policy.project_id != item.project_id:
            continue
        if policy.priorities and item.priority not in {str(p) for p in policy.priorities}:
            continue
        if policy.issue_type_ids and (
            item.type_id is None
            or str(item.type_id) not in {str(t) for t in policy.issue_type_ids}
        ):
            continue
        return policy
    return None


async def enabled_policies(session: AsyncSession, project_id: uuid.UUID) -> list[SlaPolicy]:
    """Enabled policies of one project in first-match order (position, created_at)."""
    result = await session.execute(
        select(SlaPolicy)
        .where(SlaPolicy.project_id == project_id, SlaPolicy.enabled.is_(True))
        .order_by(SlaPolicy.position, SlaPolicy.created_at)
    )
    return list(result.scalars())


async def matched_policy(session: AsyncSession, item: WorkItem) -> SlaPolicy | None:
    """The one policy governing this item, or None (spec 63 first-match against
    the item's project's policies — spec 67)."""
    return first_match(await enabled_policies(session, item.project_id), item)


async def matched_policies(
    session: AsyncSession, items: Sequence[WorkItem]
) -> dict[uuid.UUID, SlaPolicy]:
    """Batch first-match: {item_id: policy} for every item that has one. Items
    may span projects — policies are fetched once per project."""
    policies_by_project: dict[uuid.UUID, list[SlaPolicy]] = {}
    for item in items:
        if item.project_id not in policies_by_project:
            policies_by_project[item.project_id] = await enabled_policies(
                session, item.project_id
            )
    matched: dict[uuid.UUID, SlaPolicy] = {}
    for item in items:
        policy = first_match(policies_by_project[item.project_id], item)
        if policy is not None:
            matched[item.id] = policy
    return matched


def ordered(policies: Sequence[SlaPolicy]) -> list[SlaPolicy]:
    """(position, created_at) order in Python — mirrors the SQL for callers
    holding already-loaded (possibly unflushed) policies."""
    return sorted(policies, key=lambda policy: (policy.position, policy.created_at or datetime.min))
