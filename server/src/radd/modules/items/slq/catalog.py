"""What SLQ can query: builtin fields, allowed operators per field and per
custom-field type, sortability, value sentinels. The compiler dispatches on this
table; unknown field or type-invalid operator -> SlqError.

Custom fields are addressed by bare registry key; a key shadowed by a builtin
name (or spelled like a keyword) is not reachable — docs/modules.md.
"""

from dataclasses import dataclass
from enum import StrEnum

from radd.modules.fields.types import FieldType

from .lexer import CompareOp

# `me` = the current user (assignee only, v1). `none` (items.filters.NONE_LITERAL)
# = unset relation (assignee/team/parent), equivalent to IS EMPTY.
ME_LITERAL = "me"


class SlqField(StrEnum):
    """Builtin queryable fields (custom fields come from the registry by key)."""

    PROJECT = "project"  # project key (FX)
    STATE = "state"  # state name ('In Progress')
    CATEGORY = "category"  # StateCategory value
    KIND = "kind"  # ItemKind value (hierarchy)
    TYPE = "type"  # issue-type name ('Bug') | none | IS [NOT] EMPTY (spec 51)
    PRIORITY = "priority"  # Priority value
    ASSIGNEE = "assignee"  # email | me | none
    REPORTER = "reporter"  # email | me | none (spec 30)
    TEAM = "team"  # team name | none
    LABEL = "label"  # = has label; != lacks; IN = has any; IS EMPTY = unlabeled
    TITLE = "title"  # ~ contains (case-insensitive) / = exact
    KEY = "key"  # item key (TD-12)
    PARENT = "parent"  # parent item key | none
    NUMBER = "number"  # per-project number
    CREATED = "created"  # date comparisons (whole-day semantics)
    UPDATED = "updated"
    CYCLE = "cycle"  # cycle name | none | IS [NOT] EMPTY
    CYCLE_STATUS = "cycle.status"
    PAST_CYCLE = "past_cycle"  # cycles the item LEFT (carryover trail, spec 56)
    RELEASE = "release"  # release version | none | IS [NOT] EMPTY
    FLAGGED = "flagged"  # first-class boolean flag: = true | = false (spec 24)
    VISIBILITY = "visibility"  # public | internal | restricted (spec 121): =, !=, IN
    STARRED = "starred"  # personal star for the requesting user: = true | = false (spec 24)
    POINTS = "points"  # story points (spec 70): comparisons + IS [NOT] EMPTY + ORDER BY
    RANK = "rank"  # manual sort key (spec 24) — ORDER BY only, no filtering
    BLOCKS = "blocks"  # IS [NOT] EMPTY = has outgoing blocks link; = key -> blocks that item
    BLOCKED = "blocked"  # IS [NOT] EMPTY = has incoming blocks link; = key -> blocked by that item
    START = "start"  # start_date comparisons + IS [NOT] EMPTY
    TARGET = "target"  # target_date comparisons + IS [NOT] EMPTY
    # Ancestor fields (spec 83, compiled in ancestors.py — filter-only, no ORDER BY).
    # `epic` = the EPIC AN ITEM BELONGS TO — an epic belongs to itself, then its
    # parent, then its grandparent (`hierarchy.nearest_epic_case`), so an epic
    # matches its own `epic.*` conditions alongside its children. `parent` above
    # stays the direct parent. Both bare forms take key | none.
    EPIC = "epic"  # epic key (self included) | none | IS [NOT] EMPTY
    EPIC_STATE = "epic.state"  # the epic's state name (case-insensitive)
    EPIC_CATEGORY = "epic.category"  # the epic's StateCategory
    EPIC_ASSIGNEE = "epic.assignee"  # email | me | none — mirrors `assignee`
    EPIC_PRIORITY = "epic.priority"  # Priority value
    PARENT_STATE = "parent.state"  # the direct parent's state name (case-insensitive)
    PARENT_CATEGORY = "parent.category"  # the direct parent's StateCategory
    PARENT_ASSIGNEE = "parent.assignee"  # email | me | none
    PARENT_PRIORITY = "parent.priority"  # Priority value


EQUALITY = frozenset({CompareOp.EQ, CompareOp.NE})
TEXTUAL = EQUALITY | {CompareOp.CONTAINS}
RANGE = EQUALITY | {CompareOp.GT, CompareOp.LT, CompareOp.GE, CompareOp.LE}


@dataclass(frozen=True)
class FieldOps:
    """The operator surface of one field: `field op value` ops, IN/NOT IN,
    IS [NOT] EMPTY, and whether ORDER BY may use it."""

    compare: frozenset[CompareOp] = frozenset()
    membership: bool = False
    empty: bool = False
    sortable: bool = False


BUILTIN_OPS: dict[SlqField, FieldOps] = {
    SlqField.PROJECT: FieldOps(EQUALITY, membership=True),
    # RADD-1176: sortable by WORKFLOW position / category TIER order — a
    # join onto states in ordering.py, never a per-row subquery (5× slower).
    SlqField.STATE: FieldOps(EQUALITY, membership=True, sortable=True),
    SlqField.CATEGORY: FieldOps(EQUALITY, membership=True, sortable=True),
    SlqField.KIND: FieldOps(EQUALITY, membership=True, sortable=True),
    SlqField.TYPE: FieldOps(EQUALITY, membership=True, empty=True),
    SlqField.PRIORITY: FieldOps(EQUALITY, membership=True, sortable=True),
    SlqField.ASSIGNEE: FieldOps(EQUALITY, membership=True, empty=True),
    SlqField.REPORTER: FieldOps(EQUALITY, membership=True, empty=True),
    SlqField.TEAM: FieldOps(EQUALITY, membership=True, empty=True),
    SlqField.LABEL: FieldOps(EQUALITY, membership=True, empty=True),
    SlqField.TITLE: FieldOps(frozenset({CompareOp.EQ, CompareOp.CONTAINS}), sortable=True),
    SlqField.KEY: FieldOps(EQUALITY, membership=True),
    SlqField.PARENT: FieldOps(EQUALITY, membership=True, empty=True),
    SlqField.NUMBER: FieldOps(RANGE, sortable=True),
    SlqField.CREATED: FieldOps(RANGE, sortable=True),
    SlqField.UPDATED: FieldOps(RANGE, sortable=True),
    SlqField.CYCLE: FieldOps(EQUALITY, empty=True),
    SlqField.CYCLE_STATUS: FieldOps(EQUALITY, membership=True),
    SlqField.PAST_CYCLE: FieldOps(EQUALITY, membership=True, empty=True),
    SlqField.RELEASE: FieldOps(EQUALITY, empty=True),
    SlqField.FLAGGED: FieldOps(EQUALITY, sortable=True),
    SlqField.VISIBILITY: FieldOps(EQUALITY, membership=True),
    SlqField.STARRED: FieldOps(EQUALITY),
    SlqField.POINTS: FieldOps(RANGE, empty=True, sortable=True),
    SlqField.RANK: FieldOps(sortable=True),  # sort-only: no compare ops
    SlqField.BLOCKS: FieldOps(frozenset({CompareOp.EQ}), empty=True),
    SlqField.BLOCKED: FieldOps(frozenset({CompareOp.EQ}), empty=True),
    SlqField.START: FieldOps(RANGE, empty=True),
    SlqField.TARGET: FieldOps(RANGE, empty=True),
    # Ancestor fields (spec 83): op surfaces mirror their item-level counterparts;
    # none are sortable, so ORDER BY rejects them like other unsupported sorts.
    SlqField.EPIC: FieldOps(EQUALITY, membership=True, empty=True),
    SlqField.EPIC_STATE: FieldOps(EQUALITY, membership=True),
    SlqField.EPIC_CATEGORY: FieldOps(EQUALITY, membership=True),
    SlqField.EPIC_ASSIGNEE: FieldOps(EQUALITY, membership=True, empty=True),
    SlqField.EPIC_PRIORITY: FieldOps(EQUALITY, membership=True),
    SlqField.PARENT_STATE: FieldOps(EQUALITY, membership=True),
    SlqField.PARENT_CATEGORY: FieldOps(EQUALITY, membership=True),
    SlqField.PARENT_ASSIGNEE: FieldOps(EQUALITY, membership=True, empty=True),
    SlqField.PARENT_PRIORITY: FieldOps(EQUALITY, membership=True),
}

# Custom fields by registry type. All support IS [NOT] EMPTY; multi_select is
# containment (= means contains) so ranges/sorting don't apply.
CF_OPS: dict[FieldType, FieldOps] = {
    FieldType.TEXT: FieldOps(TEXTUAL, membership=True, empty=True, sortable=True),
    FieldType.URL: FieldOps(TEXTUAL, membership=True, empty=True, sortable=True),
    FieldType.USER: FieldOps(EQUALITY, membership=True, empty=True, sortable=True),
    FieldType.SELECT: FieldOps(TEXTUAL, membership=True, empty=True, sortable=True),
    FieldType.MULTI_SELECT: FieldOps(EQUALITY, membership=True, empty=True),
    FieldType.NUMBER: FieldOps(RANGE, empty=True, sortable=True),
    FieldType.DURATION: FieldOps(RANGE, empty=True, sortable=True),
    FieldType.DATE: FieldOps(RANGE, empty=True, sortable=True),
    FieldType.BOOLEAN: FieldOps(EQUALITY, empty=True, sortable=True),
}
