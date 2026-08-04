"""ORDER BY compilation. Sortable builtins map to columns (priority/kind by enum
rank); sortable custom fields sort on `->>` with a per-type cast. Everything else
is a position-carrying SlqError.
"""

from typing import Any

from sqlalchemy import ColumnElement, Date, Numeric, case

from radd.modules.fields.types import FieldType

from ..enums import ItemKind, Priority
from ..models import WorkItem
from .catalog import BUILTIN_OPS, CF_OPS, SlqField
from .errors import SlqError, unknown_field
from .helpers import Context
from .parser import OrderTerm

_PRIORITY_RANK = {priority.value: rank for rank, priority in enumerate(Priority)}
_KIND_RANK = {kind.value: rank for rank, kind in enumerate(ItemKind)}

_SORT_COLUMNS = {
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


def order_clause(ctx: Context, term: OrderTerm) -> ColumnElement[Any]:
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
    return column.desc() if term.descending else column.asc()


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
