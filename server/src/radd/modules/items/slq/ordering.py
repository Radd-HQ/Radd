"""ORDER BY compilation. Sortable builtins map to columns (priority/kind by enum
rank; state/category by the joined workflow rows, RADD-1176); sortable custom
fields sort on `->>` with a per-type cast. Everything else is a
position-carrying SlqError.

A sort term compiles to a TUPLE of columns (most are one), and the terms that
reach past `work_items` declare the JOIN they need through `order_joins`, which
the statement builders apply. Measured on the 503k-item seed: the join costs the
same as the priority CASE sort (57 vs 53 ms for a 200-row page); a correlated
subquery per row costs 261 ms, which is why that shape is not an option here.
"""

from typing import Any

from sqlalchemy import ColumnElement, Date, Numeric, case

from radd.modules.fields.types import FieldType

from radd.modules.workflow.models import State, StateCategoryDef

from ..enums import ItemKind, Priority
from ..models import WorkItem
from .catalog import BUILTIN_OPS, CF_OPS, SlqField
from .errors import SlqError, unknown_field
from .helpers import Context
from .parser import OrderTerm

_PRIORITY_RANK = {priority.value: rank for rank, priority in enumerate(Priority)}
_KIND_RANK = {kind.value: rank for rank, kind in enumerate(ItemKind)}

_SORT_COLUMNS: dict[SlqField, tuple[ColumnElement[Any], ...]] = {
    # `state`: the workflow's own order — the position states are dragged into
    # on Settings → Workflow, which the board columns already follow. Name as
    # the tiebreak, for all-projects views where workflows share positions.
    SlqField.STATE: (State.position, State.name),
    # `category`: the tier order (backlog → todo → in progress → done →
    # canceled), then the state's position within the tier.
    SlqField.CATEGORY: (StateCategoryDef.position, State.position, State.name),
    SlqField.CREATED: WorkItem.created_at,
    SlqField.UPDATED: WorkItem.updated_at,
    SlqField.NUMBER: WorkItem.number,
    SlqField.TITLE: WorkItem.title,
    SlqField.PRIORITY: case(_PRIORITY_RANK, value=WorkItem.priority),
    SlqField.KIND: case(_KIND_RANK, value=WorkItem.kind),
    SlqField.FLAGGED: WorkItem.flagged,
    SlqField.RANK: WorkItem.rank,
    SlqField.POINTS: WorkItem.estimate_points,
}


#: (target, on-clause) the state-backed sorts need; applied by every statement
#: builder that consumes `CompiledQuery.joins`. The category sort needs both.
_STATE_JOIN = (State, State.id == WorkItem.state_id)
_CATEGORY_JOIN = (StateCategoryDef, StateCategoryDef.key == State.category_key)
_ORDER_JOINS: dict[SlqField, tuple[tuple[Any, Any], ...]] = {
    SlqField.STATE: (_STATE_JOIN,),
    SlqField.CATEGORY: (_STATE_JOIN, _CATEGORY_JOIN),
}


def order_joins(terms: tuple[OrderTerm, ...]) -> tuple[tuple[Any, Any], ...]:
    """The joins the sort terms reach through, deduped in first-use order."""
    joins: list[tuple[Any, Any]] = []
    for term in terms:
        try:
            builtin = SlqField(term.field)
        except ValueError:
            continue
        for join in _ORDER_JOINS.get(builtin, ()):
            if join not in joins:
                joins.append(join)
    return tuple(joins)


def order_clause(ctx: Context, term: OrderTerm) -> tuple[ColumnElement[Any], ...]:
    if term.field in ctx.denied_fields:
        # RADD-840: sorting by a hidden field leaks its ordering — same oracle.
        raise SlqError(
            f"field '{term.field}' is read-restricted for you", term.field_position
        )
    try:
        builtin = SlqField(term.field)
    except ValueError:
        column = _cf_sort_column(ctx, term)
    else:
        if not BUILTIN_OPS[builtin].sortable:
            raise SlqError(f"field '{term.field}' is not sortable", term.field_position)
        column = _SORT_COLUMNS[builtin]
    columns = column if isinstance(column, tuple) else (column,)
    return tuple(c.desc() if term.descending else c.asc() for c in columns)


def _cf_sort_column(ctx: Context, term: OrderTerm) -> ColumnElement[Any]:
    definition = ctx.definitions_by_key.get(term.field)
    if definition is None:
        raise unknown_field(term.field, term.field_position, ctx.field_names)
    field_type = FieldType(definition.type)
    if not CF_OPS[field_type].sortable:
        raise SlqError(f"field '{term.field}' is not sortable", term.field_position)
    json_value = WorkItem.custom_fields[definition.key]
    if field_type in (FieldType.NUMBER, FieldType.DURATION):
        return json_value.astext.cast(Numeric)
    if field_type is FieldType.DATE:
        return json_value.astext.cast(Date)
    return json_value.astext
