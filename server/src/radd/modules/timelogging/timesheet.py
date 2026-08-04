"""Timesheet aggregation — flat worklog entries in a window, for the report views.

Returns entries (not pre-pivoted cells) so one query serves every presentation the
UI needs: day/week/month grids and drill-down by day, employee, or issue. Recomputed
per request (no materialization), like the reporting module — fine at prototype scale.

Joins work_items/projects read-only to filter by project and to build issue
keys — a tolerated inward read of dependency tables (timelogging depends on both),
mirroring how reporting reads the events table directly.
"""

import uuid
from datetime import date

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.auth import authz, service as auth_service
from radd.modules.auth.models import User
from radd.modules.items import service as items_service
from radd.modules.items.models import WorkItem
from radd.modules.projects import service as projects_service

from . import categories
from .models import ItemEstimate, Worklog
from .schemas import CategoryRef, ItemRef, Timesheet, TimesheetEntry, UserRef


async def build(
    session: AsyncSession,
    start: date,
    end: date,
    *,
    actor: User,
    project_id: uuid.UUID | None = None,
    user_ids: set[uuid.UUID] | None = None,
    where: ColumnElement[bool] | None = None,
) -> Timesheet:
    # RADD-839: every row carries an issue key+title, so the sheet is bounded by
    # the ACTOR's readable projects — even for a timesheet.view holder, whose
    # authority is "everyone's hours", not "projects I can't read". Required
    # parameter on purpose: a caller that forgets fails to compile, not open.
    readable = frozenset(await authz.readable_projects(session, actor))
    projects = await projects_service.list_projects(session)
    project_key = {p.id: p.key for p in projects if p.id in readable}
    if project_id is not None:
        project_key = {project_id: project_key[project_id]} if project_id in project_key else {}
    if not project_key or (user_ids is not None and not user_ids):
        return Timesheet(start=start, end=end, total_seconds=0, entries=[])

    # Item-bound rows scope through their item's project; itemless rows (spec 59)
    # carry an optional project anchor. A project filter keeps itemless rows only
    # when they're anchored to that project (general time belongs to no project,
    # so it drops out of project-filtered views). Unfiltered views keep general
    # rows (no project to leak) and drop rows anchored to unreadable projects.
    itemless = and_(
        Worklog.item_id.is_(None),
        (Worklog.project_id == project_id)
        if project_id is not None
        else or_(Worklog.project_id.is_(None), Worklog.project_id.in_(project_key.keys())),
    )
    stmt = (
        select(Worklog, WorkItem.number, WorkItem.title, WorkItem.project_id)
        .join(WorkItem, Worklog.item_id == WorkItem.id, isouter=True)
        .where(or_(WorkItem.project_id.in_(project_key.keys()), itemless))
        .where(Worklog.worked_on >= start, Worklog.worked_on <= end)
        .order_by(Worklog.worked_on, WorkItem.project_id, WorkItem.number)
    )
    if user_ids is not None:
        stmt = stmt.where(Worklog.author_id.in_(user_ids))
    # Ad-hoc worklog SLQ (spec 98) ANDs onto the scope filters — it narrows what
    # you already have rights to see, it never widens it.
    if where is not None:
        stmt = stmt.where(where)

    rows = (await session.execute(stmt)).all()
    worklogs = [row[0] for row in rows]
    authors = await auth_service.users_by_ids(session, {w.author_id for w in worklogs})
    cats = await categories.categories_by_ids(
        session, {w.category_id for w in worklogs if w.category_id}
    )
    # Itemless project labels ignore the project FILTER but stay bounded by
    # readability (RADD-839).
    all_keys = {p.id: p.key for p in projects if p.id in readable}
    # The epic per logged item, batched through items' public seam — the
    # timesheet can group by epic without learning the hierarchy itself. An epic
    # in an unreadable project is dropped (its ref is a key+title); EpicRef
    # carries no project id, so the key prefix is the join.
    readable_prefixes = set(all_keys.values())
    epics = await items_service.epics_for_items(
        session, {w.item_id for w in worklogs if w.item_id}
    )
    epics = {
        item_id: epic
        for item_id, epic in epics.items()
        if epic.key.rpartition("-")[0] in readable_prefixes
    }

    entries: list[TimesheetEntry] = []
    total = 0
    for worklog, number, title, proj_id in rows:
        total += worklog.time_spent_seconds
        author = authors.get(worklog.author_id)
        category = cats.get(worklog.category_id) if worklog.category_id else None
        item = (
            ItemRef(
                id=worklog.item_id,
                key=f"{project_key[proj_id]}-{number}",
                title=title,
                project_key=project_key[proj_id],
            )
            if worklog.item_id is not None
            else None
        )
        entries.append(
            TimesheetEntry(
                id=worklog.id,
                worked_on=worklog.worked_on,
                time_spent_seconds=worklog.time_spent_seconds,
                user=UserRef(id=worklog.author_id, name=author.name if author else "?"),
                item=item,
                epic=_epic_ref(epics.get(worklog.item_id) if worklog.item_id else None),
                project_key=(
                    item.project_key
                    if item
                    else all_keys.get(worklog.project_id) if worklog.project_id else None
                ),
                category=CategoryRef(id=category.id, name=category.name) if category else None,
                note=worklog.note,
            )
        )
    return Timesheet(start=start, end=end, total_seconds=total, entries=entries)


async def cycle_time_totals(
    session: AsyncSession,
    cycle_id: uuid.UUID,
    *,
    assignee_id: uuid.UUID | None = None,
    team_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
) -> tuple[int, int, int]:
    """(estimate, logged, remaining) seconds across a cycle's unarchived items — the
    cycle-page stats seam (same read-only WorkItem join this module already does for
    the timesheet). Remaining = Σ (estimate − logged) over estimated items — negative
    once the cycle is over-logged (the UI shows the overrun in red), matching the
    per-item remaining semantics. Worklogs on unestimated items don't subtract."""
    items_stmt = select(WorkItem.id).where(
        WorkItem.cycle_id == cycle_id, WorkItem.archived_at.is_(None)
    )
    if assignee_id is not None:
        items_stmt = items_stmt.where(WorkItem.assignee_id == assignee_id)
    if team_id is not None:
        items_stmt = items_stmt.where(WorkItem.team_id == team_id)
    if project_id is not None:
        items_stmt = items_stmt.where(WorkItem.project_id == project_id)
    item_ids = set((await session.execute(items_stmt)).scalars())
    if not item_ids:
        return 0, 0, 0
    estimates = {
        item_id: seconds
        for item_id, seconds in (
            await session.execute(
                select(ItemEstimate.item_id, ItemEstimate.original_estimate_seconds).where(
                    ItemEstimate.item_id.in_(item_ids)
                )
            )
        ).all()
    }
    logged_by_item: dict[uuid.UUID, int] = {
        item_id: seconds
        for item_id, seconds in (
            await session.execute(
                select(Worklog.item_id, func.sum(Worklog.time_spent_seconds))
                .where(Worklog.item_id.in_(item_ids))
                .group_by(Worklog.item_id)
            )
        ).all()
    }
    estimate = sum(estimates.values())
    logged = sum(logged_by_item.values())
    remaining = sum(
        seconds - logged_by_item.get(item_id, 0) for item_id, seconds in estimates.items()
    )
    return estimate, logged, remaining


def _epic_ref(epic: items_service.EpicRef | None) -> ItemRef | None:
    """The epic as an ItemRef — same shape as `item`, so the client's grouping
    code treats the two identically."""
    if epic is None:
        return None
    return ItemRef(
        id=epic.id, key=epic.key, title=epic.title, project_key=epic.key.rpartition("-")[0]
    )
