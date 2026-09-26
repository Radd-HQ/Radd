from dataclasses import dataclass
from enum import StrEnum

from radd.modules.fields.types import FieldType


class StateCategory(StrEnum):
    """Fixed categories (Linear model): analytics, boards, and rollover key off these.

    State *names* within a category are per-project data.
    """

    TRIAGE = "triage"
    BACKLOG = "backlog"
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELED = "canceled"


@dataclass(frozen=True)
class DefaultState:
    name: str
    category: StateCategory
    is_default: bool = False  # the state newly created items land in


# Seeded into every new project (mirrors the studio's actual Jira workflow).
DEFAULT_STATES: tuple[DefaultState, ...] = (
    DefaultState("Triage", StateCategory.TRIAGE, is_default=True),
    DefaultState("Backlog", StateCategory.BACKLOG),
    DefaultState("Todo", StateCategory.TODO),
    DefaultState("In Progress", StateCategory.IN_PROGRESS),
    DefaultState("Code Review", StateCategory.IN_PROGRESS),
    DefaultState("Done", StateCategory.DONE),
    DefaultState("Canceled", StateCategory.CANCELED),
)


class StateEvent(StrEnum):
    CREATED = "state.created"
    UPDATED = "state.updated"
    DELETED = "state.deleted"  # spec 87 — refused while items or the default flag point at it
    # A category row edited; every state classified under it re-derives.
    CATEGORY_UPDATED = "state_category.updated"


class StateEntity(StrEnum):
    STATE = "state"
    STATE_CATEGORY = "state_category"


class TransitionMode(StrEnum):
    """Enforcement level for workflow transitions (spec 61), resolved per item
    project through the scalar-settings cascade (`workflow_transition_mode`)."""

    OFF = "off"  # feature disabled, nothing enforced (the default)
    GUARDS = "guards"  # state changes allowed unless a matching row's rules fail
    STRICT = "strict"  # + when a project has rows, only defined (from, to) pairs move


class TransitionCheck(StrEnum):
    """The checks WORKFLOW evaluates itself (`rules` = [{check, params}]). Any other
    `check` key is served by a plugin through the kernel TRANSITION_CHECK socket
    (approvals answers `require_approval`), so a new gate is a provider, never an edit here."""

    # params {"kind": "builtin"|"custom", "key", "op", "type"?, "values"?, "display"?}
    # — one field condition (spec 107). `type` is snapshotted for custom fields
    # (comparison + phrasing); `display` carries human names for id-valued
    # `values` (cosmetic, failure strings only).
    REQUIRE_FIELD = "require_field"
    REQUIRE_RESOLVED_THREADS = "require_resolved_threads"
    # the item has a release (on-release rows always add this rule).
    REQUIRE_RELEASE = "require_release"


class ConditionKind(StrEnum):
    """What a require_field condition addresses."""

    BUILTIN = "builtin"  # a WorkItem builtin (or the estimate/comment specials)
    CUSTOM = "custom"  # a field-registry key


class ConditionOp(StrEnum):
    """Operators a require_field condition may use (subset per field type —
    see BUILTIN_OPS / ops_for_field_type)."""

    SET = "set"  # non-empty
    EMPTY = "empty"  # empty
    IS = "is"  # value ∈ values (multi-valued fields: any overlap)
    IS_NOT = "is_not"  # value ∉ values (empty passes — nothing isn't the value)
    GTE = "gte"  # numbers: >= values[0]; dates: on or after
    LTE = "lte"  # numbers: <= values[0]; dates: on or before


class BuiltinField(StrEnum):
    """Builtin condition subjects (spec 107). `estimate`/`comment` live in other
    modules and only answer set/empty — they ride the same rule shape so the
    editor shows ONE unified condition list."""

    ASSIGNEE = "assignee"
    REPORTER = "reporter"
    TEAM = "team"
    PRIORITY = "priority"
    LABELS = "labels"
    TYPE = "type"  # issue type (spec 51)
    KIND = "kind"  # hierarchy axis: epic/issue/subtask
    CYCLE = "cycle"
    RELEASE = "release"
    START_DATE = "start_date"
    TARGET_DATE = "target_date"
    ESTIMATE = "estimate"  # an item_estimates row (timelogging seam)
    COMMENT = "comment"  # ≥1 comment (comments seam)


BUILTIN_LABELS: dict[BuiltinField, str] = {
    BuiltinField.ASSIGNEE: "Assignee",
    BuiltinField.REPORTER: "Reporter",
    BuiltinField.TEAM: "Team",
    BuiltinField.PRIORITY: "Priority",
    BuiltinField.LABELS: "Labels",
    BuiltinField.TYPE: "Issue type",
    BuiltinField.KIND: "Kind",
    BuiltinField.CYCLE: "Cycle",
    BuiltinField.RELEASE: "Release",
    BuiltinField.START_DATE: "Start date",
    BuiltinField.TARGET_DATE: "Target date",
    BuiltinField.ESTIMATE: "Estimate",
    BuiltinField.COMMENT: "Comment",
}

_MEMBERSHIP_OPS = frozenset(
    {ConditionOp.SET, ConditionOp.EMPTY, ConditionOp.IS, ConditionOp.IS_NOT}
)
_PRESENCE_OPS = frozenset({ConditionOp.SET, ConditionOp.EMPTY})
_RANGE_OPS = frozenset(
    {ConditionOp.SET, ConditionOp.EMPTY, ConditionOp.GTE, ConditionOp.LTE}
)

BUILTIN_OPS: dict[BuiltinField, frozenset[ConditionOp]] = {
    BuiltinField.ASSIGNEE: _MEMBERSHIP_OPS,
    BuiltinField.REPORTER: _MEMBERSHIP_OPS,
    BuiltinField.TEAM: _MEMBERSHIP_OPS,
    BuiltinField.PRIORITY: _MEMBERSHIP_OPS,
    BuiltinField.LABELS: _MEMBERSHIP_OPS,
    BuiltinField.TYPE: _MEMBERSHIP_OPS,
    BuiltinField.KIND: _MEMBERSHIP_OPS,
    BuiltinField.CYCLE: _MEMBERSHIP_OPS,
    BuiltinField.RELEASE: _MEMBERSHIP_OPS,
    BuiltinField.START_DATE: _RANGE_OPS,
    BuiltinField.TARGET_DATE: _RANGE_OPS,
    BuiltinField.ESTIMATE: _PRESENCE_OPS,
    BuiltinField.COMMENT: _PRESENCE_OPS,
}

# Builtins whose comparison/phrasing is date-like (ISO strings order correctly).
DATE_BUILTINS = frozenset({BuiltinField.START_DATE, BuiltinField.TARGET_DATE})


def ops_for_field_type(field_type: str) -> frozenset[ConditionOp]:
    """Allowed operators for a CUSTOM field's registry type."""
    if field_type in (FieldType.NUMBER.value, FieldType.DURATION.value):
        return _MEMBERSHIP_OPS | _RANGE_OPS
    if field_type == FieldType.DATE.value:
        return _RANGE_OPS
    if field_type == FieldType.BOOLEAN.value:
        return frozenset({ConditionOp.SET, ConditionOp.EMPTY, ConditionOp.IS})
    return _MEMBERSHIP_OPS  # text, select, multi_select, user, url


class TransitionEvent(StrEnum):
    CREATED = "workflow_transition.created"
    UPDATED = "workflow_transition.updated"
    DELETED = "workflow_transition.deleted"


class TransitionEntity(StrEnum):
    TRANSITION = "workflow_transition"
