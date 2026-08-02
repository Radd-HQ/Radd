"""The worklog dialect's field surface.

Rooted at the WORKLOG, so its own columns are bare (`author`, `category`) exactly
as item queries say `priority` rather than `item_priority`. The root is implied
by which dialect you are in; prefixing it would be noise on every term.

`issue` is the one relational field. It carries three forms, and the third is
what keeps this dialect small:

    issue IS EMPTY          -- general worklogs (spec 59): no item to name
    issue = DEV-123         -- a specific issue by key
    issue.<anything>        -- DELEGATED to the item dialect

The delegation means this module never restates an item's field surface. It
inherits builtins, custom fields (`issue.cf.render_farm`), ancestors, labels and
plugin fields (`issue.logged_by`) permanently, with nothing to keep in sync —
the alternative was a second copy of the item catalog that would drift.
"""

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
    # `issue` also answers IS EMPTY — the reason general worklogs are reachable
    # at all, and the reason this dialect exists rather than an item-rooted one.
    WorklogField.ISSUE: FieldOps(
        compare=frozenset({CompareOp.EQ, CompareOp.NE}), membership=True, empty=True
    ),
    WorklogField.PROJECT: FieldOps(
        compare=frozenset({CompareOp.EQ, CompareOp.NE}), membership=True, empty=True
    ),
    WorklogField.AUTHOR: _EQUALITY,
    WorklogField.CATEGORY: FieldOps(
        compare=frozenset({CompareOp.EQ, CompareOp.NE}), membership=True, empty=True
    ),
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
