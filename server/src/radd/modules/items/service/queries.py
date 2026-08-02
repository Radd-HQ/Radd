import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from radd.config import settings
from radd.exceptions import ConflictError, NotFoundError
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project
from radd.modules.workflow.models import State
from radd.modules.workflow.types import StateCategory

from ..enums import ItemEntity
from ..hierarchy import nearest_epic_case
from ..models import ItemKeyAlias, WorkItem


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def require_item(session: AsyncSession, item_id: uuid.UUID) -> WorkItem:
    """Fetch a raw item or 404 — the cheap existence check other modules build on."""
    item = await session.get(WorkItem, item_id)
    if item is None:
        raise NotFoundError(ItemEntity.ITEM, item_id)
    return item


async def items_by_ids(
    session: AsyncSession, ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, WorkItem]:
    """Batch fetch for stream/engine consumers (SLA evaluation, spec 30)."""
    id_list = list(ids)
    if not id_list:
        return {}
    result = await session.execute(select(WorkItem).where(WorkItem.id.in_(id_list)))
    return {item.id: item for item in result.scalars()}


@dataclass(frozen=True)
class EpicRef:
    """The epic an item belongs to (ITSELF when the item is an epic), flattened
    for consumers that group by it (the timesheet). `key` is the addressable
    TD-1234 form."""

    id: uuid.UUID
    key: str
    title: str


async def epics_for_items(
    session: AsyncSession, ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, EpicRef]:
    """Nearest epic ancestor per item, batched (no N+1).

    The hierarchy is epic <- issue <- subtask (max depth 3), so the walk is at
    most two hops and resolves in ONE query via an aliased parent/grandparent
    chain — the same shape `slq/ancestors.py` uses for `epic.*`, as a batch seam
    rather than a correlated subquery. Both share `hierarchy.nearest_epic_case`,
    so an item that IS an epic maps to itself in both (time logged directly on
    an epic belongs under that epic, not under "no epic"). Items with no epic
    are simply absent from the result, which callers render as their own bucket.
    """
    id_list = list(ids)
    if not id_list:
        return {}
    child = aliased(WorkItem)
    parent = aliased(WorkItem)
    grandparent = aliased(WorkItem)
    epic = aliased(WorkItem)
    nearest = nearest_epic_case(child, parent, grandparent)
    stmt = (
        select(child.id, epic.id, Project.key, epic.number, epic.title)
        .select_from(child)
        .outerjoin(parent, parent.id == child.parent_id)
        .outerjoin(grandparent, grandparent.id == parent.parent_id)
        .join(epic, epic.id == nearest)
        .join(Project, Project.id == epic.project_id)
        .where(child.id.in_(id_list))
    )
    rows = (await session.execute(stmt)).all()
    return {
        child_id: EpicRef(id=epic_id, key=f"{project_key}-{number}", title=title)
        for child_id, epic_id, project_key, number, title in rows
    }


async def item_ids_for_projects(
    session: AsyncSession, project_ids: Iterable[uuid.UUID]
) -> list[uuid.UUID]:
    """Every ACTIVE (non-archived) item id in the given projects — the SLA
    engine's candidate scope."""
    id_list = list(project_ids)
    if not id_list:
        return []
    result = await session.execute(
        select(WorkItem.id).where(
            WorkItem.project_id.in_(id_list), WorkItem.archived_at.is_(None)
        )
    )
    return list(result.scalars())


# --- key resolution ---


def _parse_key(key: str) -> tuple[str, int] | None:
    """'TD-1234' -> ('TD', 1234). None if malformed (project keys have no dashes)."""
    prefix, _, number = key.rpartition("-")
    if not prefix or not number.isdigit():
        return None
    return prefix, int(number)


async def _alias_item(session: AsyncSession, key: str) -> WorkItem | None:
    """Key-alias fallback (spec 68): an item bulk-moved to another project keeps
    resolving under its pre-move key."""
    alias = await session.get(ItemKeyAlias, key.upper())
    return None if alias is None else await session.get(WorkItem, alias.item_id)


async def find_item_by_key(session: AsyncSession, key: str) -> WorkItem | None:
    """Raw key→item resolver WITHOUT an RBAC actor — for trusted connectors
    (spec 31) mapping external references like `TD-123`. First match wins on
    the duplicate-key edge (same rule as get_item_by_key)."""
    parsed = _parse_key(key)
    if parsed is None:
        return None
    project_key, number = parsed
    item = await session.scalar(
        select(WorkItem)
        .join(Project, Project.id == WorkItem.project_id)
        .where(Project.key == project_key.upper(), WorkItem.number == number)
        .limit(1)
    )
    return item if item is not None else await _alias_item(session, key)


# --- reporting/stats seams ---


async def estimate_points_by_ids(
    session: AsyncSession, ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, float]:
    """Current estimate_points per item, unset items omitted (spec 70) — the
    reporting module's points measure reads through this seam. Points at report
    time are CURRENT values (no as-of-completion snapshot, same simplification
    velocity already makes for assignment)."""
    id_list = list(ids)
    if not id_list:
        return {}
    rows = await session.execute(
        select(WorkItem.id, WorkItem.estimate_points).where(
            WorkItem.id.in_(id_list), WorkItem.estimate_points.is_not(None)
        )
    )
    return {item_id: float(points) for item_id, points in rows.all()}


async def cycle_points_totals(
    session: AsyncSession,
    cycle_id: uuid.UUID,
    *,
    assignee_id: uuid.UUID | None = None,
    team_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
) -> tuple[float, float]:
    """(points_total, points_done) over a cycle's unarchived items (spec 70) —
    done = items sitting in a done-category state. Honors the same filters as
    cycle_state_category_counts; unestimated items count as 0."""
    stmt = (
        select(
            func.coalesce(func.sum(WorkItem.estimate_points), 0.0),
            func.coalesce(
                func.sum(WorkItem.estimate_points).filter(
                    State.category == StateCategory.DONE.value
                ),
                0.0,
            ),
        )
        .join(State, WorkItem.state_id == State.id)
        .where(WorkItem.cycle_id == cycle_id, WorkItem.archived_at.is_(None))
    )
    if assignee_id is not None:
        stmt = stmt.where(WorkItem.assignee_id == assignee_id)
    if team_id is not None:
        stmt = stmt.where(WorkItem.team_id == team_id)
    if project_id is not None:
        stmt = stmt.where(WorkItem.project_id == project_id)
    total, done = (await session.execute(stmt)).one()
    return round(float(total), 1), round(float(done), 1)


async def count_items_assigned_to_team(session: AsyncSession, team_id: uuid.UUID) -> int:
    """How many items name this team. `work_items.team_id` is RESTRICT, so the
    teams module asks before deleting rather than letting the FK raise a 500."""
    total = await session.scalar(
        select(func.count()).select_from(WorkItem).where(WorkItem.team_id == team_id)
    )
    return int(total or 0)


async def count_items_in_state(session: AsyncSession, state_id: uuid.UUID) -> int:
    """How many items (archived included — they still reference the row) sit in a
    state. The workflow module's delete guard calls this: modules ask each other
    through public service functions, never by reading each other's tables."""
    total = await session.scalar(
        select(func.count()).select_from(WorkItem).where(WorkItem.state_id == state_id)
    )
    return int(total or 0)


async def cycle_state_category_counts(
    session: AsyncSession,
    cycle_id: uuid.UUID,
    *,
    assignee_id: uuid.UUID | None = None,
    team_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
) -> dict[str, int]:
    """Cycle-page stats seam: unarchived item counts per state category, honoring
    the same assignee/team filters the page applies to its list. `project_id`
    narrows an all-projects cycle to one project's slice — project-scoped
    surfaces (planning page, project views) must not show other projects' totals."""
    stmt = (
        select(State.category, func.count())
        .join(WorkItem, WorkItem.state_id == State.id)
        .where(WorkItem.cycle_id == cycle_id, WorkItem.archived_at.is_(None))
    )
    if assignee_id is not None:
        stmt = stmt.where(WorkItem.assignee_id == assignee_id)
    if team_id is not None:
        stmt = stmt.where(WorkItem.team_id == team_id)
    if project_id is not None:
        stmt = stmt.where(WorkItem.project_id == project_id)
    stmt = stmt.group_by(State.category)
    return {category: count for category, count in (await session.execute(stmt)).all()}


# --- manual ranking (spec 24) + number allocation ---


async def _next_rank(session: AsyncSession) -> float:
    """A rank above every existing item — new items land at the TOP of the manual
    order (rank ascending = newest first, matching the old created-desc default)."""
    current_min = (await session.execute(select(func.min(WorkItem.rank)))).scalar()
    return (current_min or 0.0) - settings.item_rank_step


async def _rebalance_ranks(session: AsyncSession) -> None:
    """Respace every item's rank by `item_rank_step` in current rank order — the
    backstop for float midpoints collapsing after many insertions between a pair."""
    rows = (
        await session.execute(select(WorkItem.id).order_by(WorkItem.rank, WorkItem.created_at))
    ).scalars()
    for index, item_id in enumerate(rows, start=1):
        await session.execute(
            update(WorkItem).where(WorkItem.id == item_id).values(rank=index * settings.item_rank_step)
        )
    await session.flush()


async def _resolve_number(session: AsyncSession, project_id: uuid.UUID, number: int | None) -> int:
    """Auto-allocate (number=None) or claim an explicit number for an import,
    advancing the project counter past it. Explicit duplicate -> 409."""
    if number is None:
        return await projects_service.allocate_item_number(session, project_id)
    dup = await session.scalar(
        select(WorkItem.id).where(WorkItem.project_id == project_id, WorkItem.number == number)
    )
    if dup is not None:
        raise ConflictError(ItemEntity.ITEM, f"number {number}")
    await projects_service.reserve_item_number(session, project_id, number)
    return number
