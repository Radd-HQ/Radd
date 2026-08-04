"""Epic progress rollup (spec 76): POST /items/rollup.

Batched descendant aggregates for a page of epic cards — counts/points by state
category plus estimate/logged time via the timelogging module when installed.
The walk is an iterative id-frontier: ONE query per depth level over the whole
requested batch (never per item; the kind hierarchy caps depth at 3), so a full
board page stays a handful of queries. Requested ids the actor can't read are
omitted from the response (the sla/batch idiom); readable ids always appear,
zeros included, so the client can distinguish "no children" from "not allowed".
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth import authz
from radd.modules.auth.models import User
from radd.modules.workflow.models import State
from radd.modules.workflow.types import StateCategory

from . import service
from .models import WorkItem
from .service.visibility import relation_read_clause
from .schemas import ItemRollup

# Rollup "done" = finished either way (Linear model): completed or canceled.
DONE_CATEGORIES = frozenset({StateCategory.DONE, StateCategory.CANCELED})


async def rollup_items(
    session: AsyncSession, actor: User, item_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, ItemRollup]:
    # One readable map gates BOTH the requested roots and every frontier level
    # (RADD-839): the walk crosses projects (the hierarchy is global), and a
    # descendant in an unreadable project must not count.
    readable_map = await authz.readable_projects(session, actor)
    readable = frozenset(readable_map)
    # RADD-817: the same relation row filter the list applies — a frontier
    # descendant the actor may not see must not count either.
    relation_clause = await relation_read_clause(session, actor, readable_map)
    item_map = await service.items_by_ids(session, list(dict.fromkeys(item_ids)))
    roots = [item.id for item in item_map.values() if item.project_id in readable]
    if roots and relation_clause is not None:
        roots = list(
            (
                await session.execute(
                    select(WorkItem.id).where(WorkItem.id.in_(roots), relation_clause)
                )
            ).scalars()
        )
    result = {root: ItemRollup() for root in roots}
    if not roots:
        return result

    # Iterative frontier: frontier maps item id -> the requested roots whose
    # subtree reached it. A child inherits its parent's root set; per-root seen
    # sets make every descendant count ONCE per root even when requested items
    # nest inside each other (an epic and its issue both on the page).
    seen: dict[uuid.UUID, set[uuid.UUID]] = {root: set() for root in roots}
    rows_by_root: dict[uuid.UUID, list[tuple[uuid.UUID, uuid.UUID, float | None]]] = {
        root: [] for root in roots
    }
    frontier: dict[uuid.UUID, set[uuid.UUID]] = {root: {root} for root in roots}
    while frontier:
        children = (
            await session.execute(
                select(
                    WorkItem.id, WorkItem.parent_id, WorkItem.state_id, WorkItem.estimate_points
                ).where(
                    WorkItem.parent_id.in_(frontier),
                    WorkItem.project_id.in_(readable),
                    *(() if relation_clause is None else (relation_clause,)),
                )
            )
        ).all()
        next_frontier: dict[uuid.UUID, set[uuid.UUID]] = {}
        for child_id, parent_id, state_id, points in children:
            new_roots = {root for root in frontier[parent_id] if child_id not in seen[root]}
            for root in new_roots:
                seen[root].add(child_id)
                rows_by_root[root].append((child_id, state_id, points))
            if new_roots:
                next_frontier.setdefault(child_id, set()).update(new_roots)
        frontier = next_frontier

    all_descendants = set().union(*seen.values())
    state_ids = {state_id for rows in rows_by_root.values() for _, state_id, _ in rows}
    categories: dict[uuid.UUID, StateCategory] = {
        state_id: StateCategory(category)
        for state_id, category in (
            await session.execute(
                select(State.id, State.category).where(State.id.in_(state_ids))
            )
        ).all()
    } if state_ids else {}

    # Time sums ride the timelogging module when it's installed (deferred
    # feature-detected import, the approvals-consume idiom) — zeros otherwise.
    estimate_by_item: dict[uuid.UUID, int] = {}
    logged_by_item: dict[uuid.UUID, int] = {}
    try:
        from radd.modules.timelogging import service as timelogging_service
    except ImportError:
        pass
    else:
        estimate_by_item = await timelogging_service.estimate_seconds_by_items(
            session, all_descendants
        )
        logged_by_item = await timelogging_service.logged_seconds_by_items(
            session, all_descendants
        )

    for root, rows in rows_by_root.items():
        rollup = result[root]
        for item_id, state_id, points in rows:
            category = categories.get(state_id)
            rollup.total += 1
            if category in DONE_CATEGORIES:
                rollup.done += 1
                if points is not None:
                    rollup.points_done += points
            elif category is StateCategory.IN_PROGRESS:
                rollup.in_progress += 1
            if points is not None:
                rollup.points_total += points
            rollup.estimate_seconds += estimate_by_item.get(item_id, 0)
            rollup.logged_seconds += logged_by_item.get(item_id, 0)
    return result
