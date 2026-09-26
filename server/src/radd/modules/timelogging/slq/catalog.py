"""The worklog dialect's fields: bare columns, plus `issue`, which answers
`IS EMPTY` (general worklogs, spec 59), `= DEV-123`, and `issue.<field>`
delegated to the item dialect (so the item catalog is never restated)."""

from enum import StrEnum

from radd.modules.items.slq import FieldOps
from radd.modules.items.slq.lexer import CompareOp

#: Prefix marking a delegated item predicate; everything after it is item SLQ.
ISSUE_PREFIX = "issue."


class WorklogField(StrEnum):
    """Queryable worklog columns. Deliberately the whole table — a worklog has
    seven columns and no custom fields, so there is no partial surface to
    explain."""

    ISSUE = "issue"
    PROJECT = "project"
    AUTHOR = "author"
    CATEGORY = "category"
    WORKED_ON = "worked_on"
    TIME = "time"
    NOTE = "note"


_EQUALITY = FieldOps(compare=frozenset({CompareOp.EQ, CompareOp.NE}), membership=True)
_NULLABLE_RELATION = FieldOps(
    compare=frozenset({CompareOp.EQ, CompareOp.NE}), membership=True, empty=True
)
_TEXT = FieldOps(compare=frozenset({CompareOp.EQ, CompareOp.NE, CompareOp.CONTAINS}))
_ORDERED = FieldOps(
    compare=frozenset(
        {
            CompareOp.EQ,
            CompareOp.NE,
            CompareOp.LT,
            CompareOp.LE,
            CompareOp.GT,
            CompareOp.GE,
        }
    ),
    sortable=True,
)

WORKLOG_OPS: dict[WorklogField, FieldOps] = {
    # `issue IS EMPTY` is why general worklogs are reachable at all.
    WorklogField.ISSUE: _NULLABLE_RELATION,
    WorklogField.PROJECT: _NULLABLE_RELATION,
    WorklogField.AUTHOR: _EQUALITY,
    WorklogField.CATEGORY: _NULLABLE_RELATION,
    WorklogField.WORKED_ON: _ORDERED,
    WorklogField.TIME: _ORDERED,
    WorklogField.NOTE: _TEXT,
}

FIELD_LABELS: dict[WorklogField, str] = {
    WorklogField.ISSUE: "Issue",
    WorklogField.PROJECT: "Project",
    WorklogField.AUTHOR: "Author",
    WorklogField.CATEGORY: "Work category",
    WorklogField.WORKED_ON: "Worked on",
    WorklogField.TIME: "Time spent",
    WorklogField.NOTE: "Note",
}
