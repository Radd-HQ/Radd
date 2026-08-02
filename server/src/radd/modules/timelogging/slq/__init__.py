"""Worklog SLQ (spec 98) — the timesheet's query dialect.

Rooted at the WORKLOG because that is what the timesheet returns; an item-rooted
query could never surface general worklogs (spec 59), which have no item to
return.

The item dialect keeps the reverse direction — `logged_by` (spec 97) lives in
`item_fields.py`: both directions of the worklog<->item relationship are this
module's business and belong together.
"""

from radd.modules.items.slq import SlqError, parse

from .catalog import FIELD_LABELS, WORKLOG_OPS, WorklogField
from .compiler import CompiledWorklogQuery, compile_worklog_query, worklog_field_names
from .item_fields import logged_by_item_ids

__all__ = [
    "FIELD_LABELS",
    "WORKLOG_OPS",
    "CompiledWorklogQuery",
    "SlqError",
    "WorklogField",
    "compile_worklog_query",
    "logged_by_item_ids",
    "parse",
    "worklog_field_names",
]
