"""Periodic SLA evaluation (specs 30/63/67): every RADD_SLA_CHECK_INTERVAL,
resolve each open item's MATCHED policy (first-match against its project's
policies), evaluate the items grouped per policy, and emit `sla.breached`
events exactly once per (item, policy, kind). Not an offset consumer — it's a
clock, not a stream reaction (breaches happen when NOTHING changes)."""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import SessionLocal
from radd.modules.items import service as items
from radd.worker import PeriodicLoop

from . import evaluation, service
from .models import SlaPolicy

logger = logging.getLogger(__name__)


async def run_once() -> int:
    emitted = 0
    async with SessionLocal() as session:
        result = await session.execute(
            select(SlaPolicy)
            .where(SlaPolicy.enabled.is_(True))
            .order_by(SlaPolicy.position, SlaPolicy.created_at)
        )
        # Spec 67: policies are project-level — group and evaluate per project.
        by_project: dict[uuid.UUID, list[SlaPolicy]] = {}
        for policy in result.scalars():
            by_project.setdefault(policy.project_id, []).append(policy)
        for project_id, policies in by_project.items():
            try:
                emitted += await _evaluate_project(session, project_id, policies)
            except Exception:
                logger.exception("sla: evaluating project %s failed", project_id)
        await session.commit()
    return emitted


async def _evaluate_project(
    session: AsyncSession, project_id: uuid.UUID, policies: list[SlaPolicy]
) -> int:
    """First-match (spec 63): each open item is evaluated under ITS policy only —
    items whose matched policy differs are never evaluated under this one.
    `policies` is one project's enabled set, pre-ordered (position, created_at)."""
    policy_by_id = {policy.id: policy for policy in policies}
    members = await service.reporter_members(session, policies)  # RADD-1299
    emitted = 0
    async for batch in items.iter_project_items(session, project_id):
        grouped: dict[uuid.UUID, list[uuid.UUID]] = {}
        for item in batch:
            policy = service.first_match(policies, item, members)
            if policy is not None:
                grouped.setdefault(policy.id, []).append(item.id)
        for policy_id, group in grouped.items():
            policy = policy_by_id[policy_id]
            terminal = await evaluation.terminal_item_ids(session, policy, group)
            open_ids = [item_id for item_id in group if item_id not in terminal]
            if not open_ids:
                continue
            evaluated = await evaluation.evaluate_items(session, policy, open_ids)
            refs = await items.item_refs(session, evaluated)
            emitted += await evaluation.sync_states(session, policy, evaluated, refs)
    return emitted


_loop = PeriodicLoop(
    run_once,
    interval=lambda: settings.sla_check_interval,
    name="sla-engine",
    enabled=lambda: settings.run_workers,  # web-only process skips (spec 48 worker split)
)

start = _loop.start
stop = _loop.stop
