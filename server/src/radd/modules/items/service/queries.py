import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import batched

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from radd.config import settings
from radd.exceptions import ConflictError, NotFoundError
from radd.modules.projects import service as projects_service
from radd.modules.projects.models import Project
from radd.modules.workflow.models import State
from radd.modules.workflow.types import StateCategory

from ..enums import FINISHED_CATEGORIES, ItemEntity
from ..hierarchy import nearest_epic_case
from ..models import ItemKeyAlias, WorkItem



async def require_item(
    session: AsyncSession, item_id: uuid.UUID, *, lock: bool = False
) -> WorkItem:
    """Fetch a raw item or 404 — the cheap existence check other modules build on.

    `lock=True` is for a WRITE (RADD-1539): the row is taken `FOR UPDATE` and
    re-read, so two requests changing one item run one after the other. Without
    it both validate a transition from the same state and both write back a
    whole `custom_fields` document — the later commit silently undoing the
    earlier one's field."""
    if lock:
        item = await session.scalar(
            select(WorkItem)
            .where(WorkItem.id == item_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    else:
        item = await session.get(WorkItem, item_id)
    if item is None:
        raise NotFoundError(ItemEntity.ITEM, item_id)
    return item


async def lock_items(session: AsyncSession, item_ids: Iterable[uuid.UUID]) -> None:
    """Take every row a multi-item write will touch, in ONE order (by id), before
    touching any: two batches that overlap then queue behind each other instead
    of each holding a row the other wants."""
    ids = sorted(set(item_ids))
    if ids:
        await session.execute(
            select(WorkItem.id).where(WorkItem.id.in_(ids)).order_by(WorkItem.id).with_for_update()
        )


async def require_item_permission(
    session: AsyncSession,
    item_id: uuid.UUID,
    actor,
    permission,
    *,
    as_missing: bool = False,
    lock: bool = False,
) -> "tuple[WorkItem, Project, frozenset]":
    """Item + project + the actor's permissions there, with `permission` required
    on the project AND for this row (relations + the restricted-row guard) — the
    one preamble item writes share, so none can forget the row gate."""
    from radd.modules.auth import authz

    from .visibility import ensure_item_relation

    item = await require_item(session, item_id, lock=lock)
    project = await projects_service.get_project(session, item.project_id)
    permissions = await authz.require(session, actor, permission, project=project)
    await ensure_item_relation(session, actor, item, permissions, permission, as_missing=as_missing)
    return item, project, permissions


async def require_readable_item(
    session: AsyncSession, item_id: uuid.UUID, actor
) -> "tuple[WorkItem, Project, frozenset]":
    """THE item-resolution seam (RADD-823): `item.read` required and the row's
    relation gate applied (a hidden item 404s). Child surfaces go through here so a
    per-item rule cannot be forgotten; callers layer their own atom on the result."""
    from radd.modules.auth.authz import Permission

    return await require_item_permission(
        session, item_id, actor, Permission.ITEM_READ, as_missing=True
    )


async def items_by_ids(
    session: AsyncSession, ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, WorkItem]:
    """Batch fetch for stream/engine consumers (SLA evaluation, spec 30)."""
    out = {}
    for batch in batched(dict.fromkeys(ids), 1000):
        result = await session.scalars(select(WorkItem).where(WorkItem.id.in_(batch)))
        out.update((item.id, item) for item in result)
    return out


async def readable_item_ids(session: AsyncSession, actor, ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
    """Authorize exact record interests, including archived detail records."""
    from radd.modules.auth import authz
    from .visibility import relation_read_clause

    projects = await authz.readable_projects(session, actor)
    if not projects:
        return set()
    clause = await relation_read_clause(session, actor, projects)
    out = set()
    for batch in batched(dict.fromkeys(ids), 1000):
        query = select(WorkItem.id).where(WorkItem.id.in_(batch), WorkItem.project_id.in_(projects))
        if clause is not None:
            query = query.where(clause)
        out.update(await session.scalars(query))
    return out


async def iter_project_items(session: AsyncSession, project_id: uuid.UUID):
    """Bounded active-item batches for workers; no full-project ID list/IN."""
    after = None
    while True:
        query = select(WorkItem).where(
            WorkItem.project_id == project_id, WorkItem.archived_at.is_(None)
        ).order_by(WorkItem.id).limit(500)
        if after is not None:
            query = query.where(WorkItem.id > after)
        batch = list(await session.scalars(query))
        if not batch:
            return
        after = batch[-1].id
        yield batch


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
    """Nearest epic per item (an epic maps to itself), batched in ONE query via
    `hierarchy.nearest_epic_case`. Items with no epic are absent."""
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
    )
    out = {}
    for batch in batched(dict.fromkeys(id_list), 1000):
        rows = await session.execute(stmt.where(child.id.in_(batch)))
        out.update(
            (child_id, EpicRef(id=epic_id, key=f"{project_key}-{number}", title=title))
            for child_id, epic_id, project_key, number, title in rows
        )
    return out


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
    out = {}
    for batch in batched(dict.fromkeys(id_list), 1000):
        rows = await session.execute(
            select(WorkItem.id, WorkItem.estimate_points).where(
                WorkItem.id.in_(batch), WorkItem.estimate_points.is_not(None)
            )
        )
        out.update((item_id, float(points)) for item_id, points in rows.all())
    return out


async def cycle_item_ids_query(
    session: AsyncSession, cycle_id: uuid.UUID, *, actor,
    assignee_id: uuid.UUID | None = None, team_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None, q: str | None = None,
):
    """Unexecuted visible-item IDs for a cycle; shared by its stats consumers."""
    from ..filters import ItemListFilters
    from .scope import visible_ids_query

    query, _ = await visible_ids_query(session, actor=actor, filters=ItemListFilters(
        project_id=project_id, cycle_ids=(str(cycle_id),),
        assignee_ids=(str(assignee_id),) if assignee_id else (),
        team_ids=(str(team_id),) if team_id else (),
    ), q=q)
    return query.order_by(None)


async def cycle_points_totals(
    session: AsyncSession,
    cycle_id: uuid.UUID,
    *,
    actor,
    q: str | None = None,
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
    stmt = stmt.where(WorkItem.id.in_(await cycle_item_ids_query(
        session, cycle_id, actor=actor, assignee_id=assignee_id, team_id=team_id,
        project_id=project_id, q=q,
    )))
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
    actor,
    q: str | None = None,
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
    stmt = stmt.where(WorkItem.id.in_(await cycle_item_ids_query(
        session, cycle_id, actor=actor, assignee_id=assignee_id, team_id=team_id,
        project_id=project_id, q=q,
    )))
    stmt = stmt.group_by(State.category)
    return {category: count for category, count in (await session.execute(stmt)).all()}


# --- manual ranking (spec 24) + number allocation ---


async def _next_rank(session: AsyncSession) -> float:
    """A rank above every existing item — new items land at the TOP of the manual
    order (rank ascending = newest first, matching the old created-desc default)."""
    current_min = (await session.execute(select(func.min(WorkItem.rank)))).scalar()
    return (current_min or 0.0) - settings.item_rank_step


async def _rebalance_ranks(session: AsyncSession) -> None:
    """Respace EVERY rank by `item_rank_step` in current order, in one set-based
    statement. The last resort only (see `_respace_after`): it rewrites the whole
    table — 503k rows on the perf seed — inside whichever request reached it."""
    ranked = select(
        WorkItem.id.label("item_id"),
        func.row_number().over(order_by=(WorkItem.rank, WorkItem.created_at)).label("rn"),
    ).subquery()
    await session.execute(
        update(WorkItem)
        .where(WorkItem.id == ranked.c.item_id)
        .values(rank=ranked.c.rn * settings.item_rank_step)
        .execution_options(synchronize_session=False)
    )
    await session.flush()


async def _respace_after(session: AsyncSession, after_id: uuid.UUID, moving_id: uuid.UUID) -> bool:
    """Open a gap right after `after_id` by spreading the rows that FOLLOW it
    (RADD-1539), instead of renumbering the whole instance-wide order inside a
    drag. Only the neighbourhood is crowded: the next `window` rows are spread
    evenly up to the rank of the row beyond them, and the window widens while
    that stretch is itself too tight to hold them. True = a gap exists.

    False = `after_id` shares its rank with more rows than the widest window
    (data seeded with one rank for everything): the caller falls back to the
    full rebalance, which is the only thing that can order such rows at all."""
    anchor = await session.scalar(select(WorkItem.rank).where(WorkItem.id == after_id))
    if anchor is None:
        return False
    window = settings.item_rank_respace_window
    while window <= settings.item_rank_respace_max:
        rows = (
            await session.execute(
                select(WorkItem.id, WorkItem.rank)
                .where(WorkItem.rank >= anchor, WorkItem.id.not_in((after_id, moving_id)))
                .order_by(WorkItem.rank, WorkItem.created_at.desc(), WorkItem.id)
                .limit(window + 1)
            )
        ).all()
        if len(rows) <= window:
            # The end of the order: nothing above to stay under.
            spacing, crowded = settings.item_rank_step, rows
        else:
            crowded, ceiling = rows[:window], rows[window].rank
            spacing = (ceiling - anchor) / (window + 2)
        # Wide enough that a midpoint between two of them is a distinct float
        # many times over; the first slot stays free for the row being placed.
        if spacing > max(abs(anchor), 1.0) * 1e-9:
            for position, row in enumerate(crowded, start=2):
                await session.execute(
                    update(WorkItem)
                    .where(WorkItem.id == row.id)
                    .values(rank=anchor + spacing * position)
                    .execution_options(synchronize_session=False)
                )
            await session.flush()
            return True
        window *= 4
    return False


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


async def project_stats(
    session: AsyncSession, project_ids: Iterable[uuid.UUID], visible
) -> dict[uuid.UUID, tuple[int, object]]:
    """`{project: (open issues, last activity)}` for a page of projects (RADD-1558).

    `visible` is the caller's own readable-items SELECT (ids), so both numbers
    describe what THAT actor can see: counting every item of a readable project
    would tell a public project's visitor how many internal issues exist and
    when one last moved."""
    ids = list(dict.fromkeys(project_ids))
    if not ids:
        return {}
    mine = WorkItem.id.in_(visible)
    open_rows = await session.execute(
        select(WorkItem.project_id, func.count())
        .join(State, State.id == WorkItem.state_id)
        .where(
            WorkItem.project_id.in_(ids),
            WorkItem.archived_at.is_(None),
            State.category.not_in([c.value for c in FINISHED_CATEGORIES]),
            mine,
        )
        .group_by(WorkItem.project_id)
    )
    opened = dict(open_rows.all())
    stats: dict[uuid.UUID, tuple[int, object]] = {}
    for project_id in ids:
        last = await session.scalar(
            select(WorkItem.updated_at)
            .where(WorkItem.project_id == project_id, mine)
            .order_by(WorkItem.updated_at.desc())
            .limit(1)
        )
        stats[project_id] = (opened.get(project_id, 0), last)
    return stats
