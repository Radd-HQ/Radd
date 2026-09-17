"""Group before paging: one bounded slice per board cell, using authorized IDs."""

import uuid

from pydantic import BaseModel, Field
from sqlalchemy import String, cast, func, literal, select, case
from sqlalchemy.orm import aliased

from radd.exceptions import ForbiddenError
from radd.modules.workflow.models import State, StateCategoryDef

from .filters import ItemListFilters, FilterParseError
from . import cursors
from .hierarchy import nearest_epic_case
from .models import WorkItem
from .schemas import ItemRead
from .service.listing import list_items
from .service.scope import visible_ids_query
from .service.visibility import denied_slq_fields
from .slq.errors import SlqError


class GroupPageRequest(BaseModel):
    project_id: uuid.UUID | None = None
    q: str = ""
    axis: str
    column_key: str | None = None
    cursor_mode: bool = False
    after: str | None = Field(None, max_length=16384)
    lane: str | None = None
    hidden_columns: list[str] = Field(default_factory=list)
    hidden_lanes: list[str] = Field(default_factory=list)
    column_order: list[str] = Field(default_factory=list)
    lane_order: list[str] = Field(default_factory=list)
    cycle_ids: list[uuid.UUID] | None = None
    cycle_scope: bool = False
    group_offset: int = Field(0, ge=0)
    item_offset: int = Field(0, ge=0)
    group_limit: int = Field(20, ge=1, le=40)
    item_limit: int = Field(25, ge=1, le=50)


class GroupCell(BaseModel):
    column: str
    lane: str
    total: int
    items: list[ItemRead]
    points: float | None = None
    next_cursor: str | None = None


class GroupPage(BaseModel):
    cells: list[GroupCell]
    total_groups: int
    column_totals: dict[str, int]
    lane_totals: dict[str, int]
    column_points: dict[str, float] | None = None


def _axis(axis, project_id, epic):
    values = {
        "state": cast(WorkItem.state_id, String) if project_id else State.name,
        "state_category": State.category_key,
        "priority": WorkItem.priority,
        "kind": WorkItem.kind,
        "assignee": func.coalesce(cast(WorkItem.assignee_id, String), "__unassigned__"),
        "team": func.coalesce(cast(WorkItem.team_id, String), "__no_team__"),
        "cycle": func.coalesce(cast(WorkItem.cycle_id, String), "__backlog__"),
        "epic": func.coalesce(cast(epic, String), "__no_epic__"),
        None: literal("__all__"),
    }
    if axis and axis.startswith("cf."):
        return func.coalesce(func.nullif(WorkItem.custom_fields[axis[3:]].astext, ""), "__none__")
    if axis not in values:
        raise SlqError(f"Unsupported grouping axis: {axis}", 0)
    return values[axis]


async def grouped_items(session, actor, data: GroupPageRequest) -> GroupPage:
    if data.after and (
        not data.cursor_mode or data.column_key is None or data.lane or data.item_offset
    ):
        raise FilterParseError("Board continuation requires one column without swimlanes or offset")
    filters = ItemListFilters(project_id=data.project_id)
    visible, order = await visible_ids_query(session, actor=actor, filters=filters, q=data.q)
    # Group values must obey the same field-read restrictions as SLQ predicates.
    from radd.modules.projects import service as projects

    project = await projects.get_project(session, data.project_id) if data.project_id else None
    denied = await denied_slq_fields(session, actor, project)
    for axis in (data.axis, data.lane):
        field = "category" if axis == "state_category" else axis
        if field and (field in denied or field.removeprefix("cf.") in denied):
            raise ForbiddenError("Grouping field is not readable")
    parent, grand = aliased(WorkItem), aliased(WorkItem)
    epic = nearest_epic_case(WorkItem, parent, grand)
    if "epic" in (data.axis, data.lane):
        readable_ancestors, _ = await visible_ids_query(
            session, actor=actor, filters=ItemListFilters(), q=""
        )
        epic = case((epic.in_(readable_ancestors), epic), else_=None)
    column, lane = _axis(data.axis, data.project_id, epic), _axis(data.lane, data.project_id, epic)
    query = (
        select(WorkItem.id, column.label("col"), lane.label("lane"))
        .join(State, State.id == WorkItem.state_id)
        .join(StateCategoryDef, StateCategoryDef.key == State.category_key)
        .where(WorkItem.id.in_(visible))
    )
    if "epic" in (data.axis, data.lane):
        query = query.outerjoin(parent, parent.id == WorkItem.parent_id).outerjoin(
            grand, grand.id == parent.parent_id
        )
    if data.column_key is not None:
        query = query.where(column == data.column_key)
    if data.hidden_columns:
        query = query.where(column.not_in(data.hidden_columns))
    if data.hidden_lanes:
        query = query.where(lane.not_in(data.hidden_lanes))
    if "cycle" in (data.axis, data.lane) and (data.cycle_scope or data.cycle_ids is not None):
        from sqlalchemy import or_, and_

        query = query.where(
            or_(
                WorkItem.cycle_id.in_(data.cycle_ids or []),
                and_(WorkItem.cycle_id.is_(None), State.category.not_in(("done", "canceled"))),
            )
        )
    ranking = (
        (*order, WorkItem.id.asc())
        if order
        else (WorkItem.rank.asc(), WorkItem.created_at.desc(), WorkItem.id.asc())
    )
    points_readable = "points" not in denied and "estimate_points" not in denied
    ranked = query.add_columns(
        (WorkItem.estimate_points if points_readable else literal(0.0)).label("points"),
        func.row_number().over(order_by=ranking).label("global_pos"),
    ).subquery()
    counts = list(
        (
            await session.execute(
                select(
                    ranked.c.col,
                    ranked.c.lane,
                    func.count(),
                    func.coalesce(func.sum(ranked.c.points), 0.0),
                )
                .group_by(ranked.c.col, ranked.c.lane)
                .order_by(func.min(ranked.c.global_pos), ranked.c.col, ranked.c.lane)
            )
        ).all()
    )
    column_rank, lane_rank = (
        {key: i for i, key in enumerate(data.column_order)},
        {key: i for i, key in enumerate(data.lane_order)},
    )
    if column_rank or lane_rank:
        counts.sort(
            key=lambda row: (
                column_rank.get(row[0], len(column_rank)),
                lane_rank.get(row[1], len(lane_rank)),
            )
        )
    chosen = counts[data.group_offset : data.group_offset + data.group_limit]
    column_totals, lane_totals = {}, {}
    column_points = {} if points_readable else None
    for col, ln, count, points in counts:
        if column_points is not None:
            column_points[col] = column_points.get(col, 0.0) + float(points)
        column_totals[col] = column_totals.get(col, 0) + count
        lane_totals[ln] = lane_totals.get(ln, 0) + count
    if not chosen:
        return GroupPage(
            cells=[],
            total_groups=len(counts),
            column_totals=column_totals,
            lane_totals=lane_totals,
            column_points=column_points,
        )
    from sqlalchemy import tuple_

    boundary_columns = [
        column.label(f"cursor_{i}") for i, (column, _) in enumerate(cursors.terms(ranking))
    ]
    scope_data = data.model_dump(
        mode="json",
        exclude={
            "after",
            "cursor_mode",
            "column_key",
            "item_offset",
            "item_limit",
            "group_offset",
            "group_limit",
        },
    )

    def cell_scope(col, ln):
        return cursors.scope_key(actor, ["board-v1", scope_data, col, ln])

    selected_query = query.where(tuple_(column, lane).in_([(col, ln) for col, ln, _, _ in chosen]))
    if data.after:
        boundary, cursor_position = cursors.decode(
            data.after, cell_scope(data.column_key, "__all__"), len(ranking)
        )
        selected_query = (
            selected_query.offset(cursor_position)
            if boundary is None
            else selected_query.where(cursors.after_clause(ranking, boundary))
        )
        fetched = list(
            (
                await session.execute(
                    selected_query.add_columns(*boundary_columns)
                    .order_by(*ranking)
                    .limit(data.item_limit + 1)
                )
            ).all()
        )
        rows = fetched[: data.item_limit]
        continued_more = len(fetched) > data.item_limit
    else:
        selected = selected_query.add_columns(
            *boundary_columns,
            func.row_number().over(partition_by=(column, lane), order_by=ranking).label("pos"),
        ).subquery()
        rows = list(
            (
                await session.execute(
                    select(selected)
                    .where(
                        selected.c.pos > data.item_offset,
                        selected.c.pos <= data.item_offset + data.item_limit,
                    )
                    .order_by(selected.c.col, selected.c.lane, selected.c.pos)
                )
            ).all()
        )
        continued_more = False
        cursor_position = data.item_offset

    def next_cursor(col, ln, count):
        cell_rows = [r for r in rows if r.col == col and r.lane == ln]
        more = continued_more if data.after else count > data.item_offset + len(cell_rows)
        if not data.cursor_mode or data.lane or not more or not cell_rows:
            return None
        return cursors.encode(
            cell_scope(col, ln),
            [getattr(cell_rows[-1], f"cursor_{i}") for i in range(len(ranking))],
            cursor_position + len(cell_rows),
        )

    ids = [row.id for row in rows]
    reads = (
        await list_items(
            session, actor=actor, filters=filters, selected_ids=ids, limit=len(ids) or 1, offset=0
        )
        if ids
        else []
    )
    by_id = {r.id: r for r in reads}
    cells = [
        GroupCell(
            column=col,
            lane=ln,
            total=count,
            next_cursor=next_cursor(col, ln, count),
            points=float(points) if points_readable else None,
            items=[by_id[r.id] for r in rows if r.col == col and r.lane == ln and r.id in by_id],
        )
        for col, ln, count, points in chosen
    ]
    return GroupPage(
        cells=cells,
        total_groups=len(counts),
        column_totals=column_totals,
        lane_totals=lane_totals,
        column_points=column_points,
    )
