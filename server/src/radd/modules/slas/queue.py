"""Triage ordering over the authorized match set, before selecting a page.

Use live evaluation, not breach bookkeeping: terminal bookkeeping can be stale
when a timer is met or the matched policy changes. Only IDs and sort keys span
the match set; item/timeline evaluation and final hydration are bounded batches.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from radd.modules.items import service as items
from radd.modules.items.filters import ItemListFilters
from radd.modules.items.models import WorkItem

from . import evaluation, service


async def queue_items(
    session, actor, *, project_id: uuid.UUID | None, q: str, limit: int, offset: int
):
    filters = ItemListFilters(project_id=project_id)
    visible, order = await items.visible_ids_query(session, actor=actor, filters=filters, q=q)
    if order:
        return await items.list_items(
            session, actor=actor, filters=filters, q=q, limit=limit, offset=offset
        )
    # Keyset traversal avoids keeping full ORM rows/timelines for the whole queue.
    last_id = None
    keys = []
    while True:
        query = (
            select(WorkItem.id, WorkItem.created_at)
            .where(WorkItem.id.in_(visible))
            .order_by(WorkItem.id)
            .limit(200)
        )
        if last_id is not None:
            query = query.where(WorkItem.id > last_id)
        batch = list((await session.execute(query)).all())
        if not batch:
            break
        ids = [r.id for r in batch]
        matched = await service.matched_policies(
            session, list((await items.items_by_ids(session, ids)).values())
        )
        policies, groups = {}, {}
        for item_id, policy in matched.items():
            policies[policy.id] = policy
            groups.setdefault(policy.id, []).append(item_id)
        facts = {}
        for policy_id, group in groups.items():
            for item_id, per_kind in (
                await evaluation.evaluate_items(session, policies[policy_id], group)
            ).items():
                open_timers = [status for _, status in per_kind.values() if status.met_at is None]
                facts[item_id] = (
                    any(s.breached for s in open_timers),
                    min(
                        (s.due_at for s in open_timers if s.due_at),
                        default=datetime.max.replace(tzinfo=UTC),
                    ),
                )
        for row in batch:
            breached, due = facts.get(row.id, (False, datetime.max.replace(tzinfo=UTC)))
            keys.append((not breached, due, row.created_at, row.id))
        last_id = batch[-1].id
    keys.sort()
    selected = [entry[-1] for entry in keys[offset : offset + limit]]
    if not selected:
        return []
    reads = await items.list_items(
        session, actor=actor, filters=filters, selected_ids=selected, limit=limit, offset=0
    )
    by_id = {row.id: row for row in reads}
    return [by_id[i] for i in selected if i in by_id]
