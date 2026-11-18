"""Timesheet aggregation: flat worklog entries in a window (not pre-pivoted
cells), so one query serves every grid and drill-down the UI pivots. Reads
work_items read-only for project scoping and issue keys (timelogging depends on items)."""

import uuid
from datetime import date

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.exceptions import RaddError
from radd.modules.auth import authz, service as auth_service
from radd.modules.auth.models import User
from radd.modules.items import service as items_service
from radd.modules.items.models import WorkItem
from radd.modules.projects import service as projects_service
from radd.modules.teams import service as teams_service
from radd.modules.teams.models import Team

from . import categories
from .models import ItemEstimate, Worklog
from .schemas import CategoryRef, ItemRef, Timesheet, TimesheetEntry, UserRef


class TimesheetTooLarge(RaddError):
    """The window, or what it holds, is more than one request may ask for (-> 422)."""


def check_window(start: date, end: date) -> None:
    days = (end - start).days + 1
    if days > settings.timesheet_max_range_days:
        raise TimesheetTooLarge(
            f"a timesheet covers at most {settings.timesheet_max_range_days} days; "
            f"{start.isoformat()} to {end.isoformat()} is {days}"
        )


async def visible_user_ids(
    session: AsyncSession, actor: User, requested: set[uuid.UUID] | None
) -> set[uuid.UUID] | None:
    """Narrow `requested` authors (None = everyone) to whose time `actor` may see.

    With timesheet.view — held GLOBALLY: one project's grant must not expose the
    instance's hours — that is whoever was asked for. Without it, their own, and
    the members of the teams they own or manage WHEN THEY ASK for them
    (RADD-1576): a sheet nobody narrowed stays their own time, so stewardship
    never widens a default."""
    if authz.Permission.TIMESHEET_VIEW in await authz.effective_permissions(session, actor):
        return requested
    if requested is None:
        return {actor.id}
    allowed = {actor.id}
    if requested - allowed:  # the team read is only paid for when others are asked for
        led = await teams_service.stewarded_teams(session, actor.id)
        allowed |= await teams_service.users_for_teams(session, [team.id for team in led])
    return requested & allowed


async def reviewable_teams(session: AsyncSession, actor: User) -> list[Team]:
    """The teams whose time `actor` may review on the Team view: every team with
    timesheet.view, otherwise the ones they own or manage (RADD-1576)."""
    if authz.Permission.TIMESHEET_VIEW in await authz.effective_permissions(session, actor):
        return await teams_service.list_teams(session)
    return await teams_service.stewarded_teams(session, actor.id)


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
    check_window(start, end)
    readable = frozenset(await authz.readable_projects(session, actor))
    projects = await projects_service.list_projects(session)
    project_key = {p.id: p.key for p in projects if p.id in readable}
    if project_id is not None:
        project_key = {project_id: project_key[project_id]} if project_id in project_key else {}
    if not project_key or (user_ids is not None and not user_ids):
        return Timesheet(start=start, end=end, total_seconds=0, entries=[])

    # Itemless rows (spec 59) carry an optional project anchor: a project filter
    # keeps only those anchored to it; unfiltered views keep unanchored general
    # rows (no project to leak) and drop rows anchored to unreadable projects.
    itemless = and_(
        Worklog.item_id.is_(None),
        (Worklog.project_id == project_id)
        if project_id is not None
        else or_(Worklog.project_id.is_(None), Worklog.project_id.in_(project_key.keys())),
    )
    stmt = (
        # Columns, not `Worklog` entities: nothing here is written back, and an
        # ORM object per row was most of the cost of a wide sheet.
        select(
            Worklog.id, Worklog.item_id, Worklog.project_id, Worklog.author_id,
            Worklog.category_id, Worklog.worked_on, Worklog.time_spent_seconds,
            Worklog.note, Worklog.external_source,
            WorkItem.number, WorkItem.title, WorkItem.project_id.label("item_project_id"),
        )
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

    # One past the bound is enough to know the sheet is over it.
    rows = (await session.execute(stmt.limit(settings.timesheet_max_entries + 1))).all()
    if len(rows) > settings.timesheet_max_entries:
        raise TimesheetTooLarge(
            f"this timesheet holds more than {settings.timesheet_max_entries:,} time logs; "
            "narrow the dates, pick a team or a project, or add a filter"
        )
    authors = await auth_service.users_by_ids(session, {w.author_id for w in rows})
    cats = await categories.categories_by_ids(
        session, {w.category_id for w in rows if w.category_id}
    )
    # Itemless project labels ignore the project FILTER but stay bounded by
    # readability (RADD-839).
    all_keys = {p.id: p.key for p in projects if p.id in readable}
    # The epic per logged item, through items' public seam. An epic in an
    # unreadable project is dropped; EpicRef has no project id, so the key prefix joins.
    readable_prefixes = set(all_keys.values())
    epics = await items_service.epics_for_items(
        session, {w.item_id for w in rows if w.item_id}
    )
    epics = {
        item_id: epic
        for item_id, epic in epics.items()
        if epic.key.rpartition("-")[0] in readable_prefixes
    }

    entries: list[TimesheetEntry] = []
    total = 0
    for worklog in rows:
        number, title, proj_id = worklog.number, worklog.title, worklog.item_project_id
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
                external_source=worklog.external_source,
            )
        )
    return Timesheet(start=start, end=end, total_seconds=total, entries=entries)


async def cycle_time_totals(
    session: AsyncSession,
    cycle_id: uuid.UUID,
    *,
    actor: User,
    assignee_id: uuid.UUID | None = None,
    team_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    q: str | None = None,
) -> tuple[int, int, int]:
    """Visible cycle time totals, aggregated in SQL without collecting item IDs.

    Remaining subtracts logged time only for estimated items, including overruns.
    The item module owns project, relation, archived and SLQ read filtering.
    """
    visible = (await items_service.cycle_item_ids_query(
        session, cycle_id, actor=actor, assignee_id=assignee_id, team_id=team_id,
        project_id=project_id, q=q,
    )).cte("cycle_visible_items")
    logged = (
        select(Worklog.item_id, func.sum(Worklog.time_spent_seconds).label("seconds"))
        .where(Worklog.item_id.in_(select(visible.c.id)))
        .group_by(Worklog.item_id).subquery()
    )
    query = (
        select(
            func.coalesce(func.sum(ItemEstimate.original_estimate_seconds), 0),
            func.coalesce(func.sum(logged.c.seconds), 0),
            func.coalesce(func.sum(ItemEstimate.original_estimate_seconds - func.coalesce(logged.c.seconds, 0)), 0),
        ).select_from(visible)
        .outerjoin(ItemEstimate, ItemEstimate.item_id == visible.c.id)
        .outerjoin(logged, logged.c.item_id == visible.c.id)
    )
    return tuple(int(value) for value in (await session.execute(query)).one())


def _epic_ref(epic: items_service.EpicRef | None) -> ItemRef | None:
    """The epic as an ItemRef — same shape as `item`, so the client's grouping
    code treats the two identically."""
    if epic is None:
        return None
    return ItemRef(
        id=epic.id, key=epic.key, title=epic.title, project_key=epic.key.rpartition("-")[0]
    )
