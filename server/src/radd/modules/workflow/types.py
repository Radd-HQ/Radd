from dataclasses import dataclass
from enum import StrEnum


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


class StateEntity(StrEnum):
    STATE = "state"
    STATE_GROUP = "state_group"


class TransitionMode(StrEnum):
    """Enforcement level for workflow transitions (spec 61), resolved per item
    project through the scalar-settings cascade (`workflow_transition_mode`)."""

    OFF = "off"  # feature disabled, nothing enforced (the default)
    GUARDS = "guards"  # state changes allowed unless a matching row's rules fail
    STRICT = "strict"  # + when a project has rows, only defined (from, to) pairs move


class TransitionCheck(StrEnum):
    """Validation rules a transition row may carry (`rules` = [{check, params}]).
    The extension point for later gates (require_permission…) — no schema change.

    Spec 107 collapsed the five legacy checks (require_assignee / require_estimate
    / require_team / require_comment / require_fields) into ONE structured
    condition check; the migration rewrote every stored rule."""

    # params {"kind": "builtin"|"custom", "key", "op", "type"?, "values"?, "display"?}
    # — one field condition (spec 107). `type` is snapshotted for custom fields
    # (comparison + phrasing); `display` carries human names for id-valued
    # `values` (cosmetic, failure strings only).
    REQUIRE_FIELD = "require_field"
    # Spec 71, reshaped by spec 107: params {"approvers": [{kind: "user"|"team",
    # id, name, required?}]} — EVERY entry must be satisfied (a user approves
    # personally; a team needs `required` approvals from current members).
    # Passes iff the item holds a consumable APPROVED request for the target
    # state (resolved via the approvals module's deferred seam).
    REQUIRE_APPROVAL = "require_approval"


class ConditionKind(StrEnum):
    """What a require_field condition addresses."""

    BUILTIN = "builtin"  # a WorkItem builtin (or the estimate/comment specials)
    CUSTOM = "custom"  # a field-registry key


class ApproverKind(StrEnum):
    """One approver entry on a require_approval rule (spec 107): a USER must
    approve personally; a TEAM needs `required` approvals from current members."""

    USER = "user"
    TEAM = "team"


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
    """Allowed operators for a CUSTOM field's registry type (fields.FieldType
    wire values — workflow stays ignorant of the fields module's enum)."""
    if field_type in ("number", "duration"):
        return _MEMBERSHIP_OPS | _RANGE_OPS
    if field_type == "date":
        return _RANGE_OPS
    if field_type == "boolean":
        return frozenset({ConditionOp.SET, ConditionOp.EMPTY, ConditionOp.IS})
    return _MEMBERSHIP_OPS  # text, select, multi_select, user, url


class TransitionEvent(StrEnum):
    CREATED = "workflow_transition.created"
    UPDATED = "workflow_transition.updated"
    DELETED = "workflow_transition.deleted"


class TransitionEntity(StrEnum):
    TRANSITION = "workflow_transition"
