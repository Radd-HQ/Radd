import uuid
from dataclasses import dataclass
from enum import StrEnum

from radd.kernel.specs import (  # the spec's own vocabulary (RADD-1467); re-exported for the module's callers
    AutomationNodeKind as AutomationNodeKind,
    NodeArity as NodeArity,
    NodePort as NodePort,
)
from radd.schedule import ScheduleKind


# A rule's trigger is an EVENT TYPE from the catalog, or one of these sentinels —
# no event names them, so the outbox consumer never starts a run from them.
class AutomationTrigger(StrEnum):
    MANUAL = "manual"
    SCHEDULE = "schedule"
    # Spec 119: runs synchronously at intake over a savepoint draft and collects
    # FINDINGS; what it governs lives in `automation_validations`.
    VALIDATE = "validate"


class ValidationTargetKind(StrEnum):
    """What a validate trigger governs. A LIST of these rides on the node, never
    three parallel scalar params: "this graph checks the Bug type in two projects
    and the incident form" is a set of scoped rows, and a single value could only
    ever hold the last one written."""

    FORM = "form"
    ISSUE_TYPE = "issue_type"
    PROJECT = "project"


class ValidationMode(StrEnum):
    """How hard a governing graph's findings bite.

    ADVISORY shows them and lets the person create anyway; REQUIRED refuses the
    creation for EVERY non-automated caller, REST and MCP included. When several
    graphs govern one draft the strictest mode wins — a required check cannot be
    softened by an advisory one that happens to be listed beside it."""

    ADVISORY = "advisory"
    REQUIRED = "required"


#: Ranked, so "strictest wins" is a max() rather than an if-chain that has to be
#: repeated wherever two verdicts meet.
VALIDATION_MODE_RANK: dict[ValidationMode, int] = {
    ValidationMode.ADVISORY: 0,
    ValidationMode.REQUIRED: 1,
}


#: The shape of a scheduled rule's `schedule` JSONB (spec 69). Promoted to the
#: shared core util by spec 99 (backups schedule the same way); re-exported here
#: so this module's own vocabulary still reads from one place.
ScheduleKind = ScheduleKind


class ConditionOperator(StrEnum):
    """The operators of the one open-ended gate, `gate.payload` ("Event value
    is"): a dotted path into the event payload, one of these, a value."""

    EQ = "eq"
    NEQ = "neq"
    IN = "in"
    NOT_IN = "not_in"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    IS_SET = "is_set"
    NOT_SET = "not_set"
    MATCHES = "matches"  # case-insensitive regex
    GT = "gt"
    LT = "lt"


class ActionType(StrEnum):
    """What a matching rule does — each dispatched through a target service.
    The first block acts ON THE TARGET ITEM (skipped, with a log, when the
    trigger resolved none); the UNIVERSAL block (spec 58b) runs for every
    matching event, item or not, with `{{token}}` templates in its params."""

    SET_STATE = "set_state"
    SET_PRIORITY = "set_priority"
    SET_ASSIGNEE = "set_assignee"
    #: Assign the next member of a named team, round-robin, skipping inactive and
    #: away accounts (RADD-1044). Item-arity like SET_ASSIGNEE — "the next
    #: member" is a per-item choice, so a set reading would pile a whole batch on
    #: one person, which is the opposite of distributing it.
    ASSIGN_ROUND_ROBIN = "assign_round_robin"
    SET_TEAM = "set_team"
    ADD_LABEL = "add_label"
    REMOVE_LABEL = "remove_label"
    SET_CYCLE = "set_cycle"
    SET_RELEASE = "set_release"
    SET_CUSTOM_FIELD = "set_custom_field"
    ADD_COMMENT = "add_comment"
    # RADD-1267: the rest of what an item can have done to it. Every field
    # `ItemUpdate` accepts, plus the verbs that are not field writes.
    SET_PARENT = "set_parent"
    SET_TYPE = "set_type"
    SET_REPORTER = "set_reporter"
    SET_DATES = "set_dates"
    SET_ESTIMATE = "set_estimate"
    SET_FLAG = "set_flag"
    SET_VISIBILITY = "set_visibility"
    LINK_ITEM = "link_item"
    ARCHIVE_ITEM = "archive_item"
    ADD_WATCHER = "add_watcher"
    MOVE_TO_PROJECT = "move_to_project"
    # Universal actions (spec 58b) — run with or without a target item.
    CREATE_ITEM = "create_item"
    SEND_WEBHOOK = "send_webhook"
    POST_CHAT = "post_chat"
    NOTIFY_USER = "notify_user"
    # RADD-1387: `send_email` and `add_participant` are no longer built in —
    # `mailintake` and `participants` contribute them under the SAME node keys
    # (`action.send_email`, `action.add_participant`), so stored graphs load
    # unchanged, and disabling either plugin takes its action with it.


class GatePerson(StrEnum):
    """Who a membership gate asks about (RADD-1498): a role on the target item
    (`PersonRole`), or the ACTOR — whoever caused the event, which is the only
    person a non-item event carries. Anything else in the param is an email."""

    REPORTER = "reporter"
    ASSIGNEE = "assignee"
    ACTOR = "actor"


class PersonRole(StrEnum):
    """A person named RELATIVE TO the target item rather than by address — what
    a person param (`notify_user`'s `user`, `add_watcher`'s, a contributed
    action's through `ctx.person`) may say instead of an email. Resolves
    against ONE item, so it only means anything at per-item arity; no item or
    nobody in the role → the action skip-logs."""

    REPORTER = "reporter"
    ASSIGNEE = "assignee"


#: Node param carrying the author's choice. Absent = the type's default, which
#: is what keeps every graph stored before this behaving exactly as it did.
ARITY_PARAM = "arity"


@dataclass(frozen=True)
class ArityRule:
    """What a node type's arity may be. `options` of length one means fixed —
    the editor shows no control, because a toggle with one setting is noise."""

    default: NodeArity
    options: tuple[NodeArity, ...]

    @property
    def configurable(self) -> bool:
        return len(self.options) > 1


#: Every action's DEFAULT arity; a stored node with no `arity` param runs as this.
ACTION_ARITY_DEFAULT: dict[ActionType, NodeArity] = {
    # Mutations of one item. Only ITEM is meaningful — there is no canonical
    # item in a set to apply them to.
    ActionType.SET_STATE: NodeArity.ITEM,
    ActionType.SET_PRIORITY: NodeArity.ITEM,
    ActionType.SET_ASSIGNEE: NodeArity.ITEM,
    # Fixed ITEM: no set reading of round-robin exists; `_check_arity` refuses `arity=set`.
    ActionType.ASSIGN_ROUND_ROBIN: NodeArity.ITEM,
    ActionType.SET_TEAM: NodeArity.ITEM,
    ActionType.ADD_LABEL: NodeArity.ITEM,
    ActionType.REMOVE_LABEL: NodeArity.ITEM,
    ActionType.SET_CYCLE: NodeArity.ITEM,
    ActionType.SET_RELEASE: NodeArity.ITEM,
    ActionType.SET_CUSTOM_FIELD: NodeArity.ITEM,
    ActionType.ADD_COMMENT: NodeArity.ITEM,
    ActionType.SET_PARENT: NodeArity.ITEM,
    ActionType.SET_TYPE: NodeArity.ITEM,
    ActionType.SET_REPORTER: NodeArity.ITEM,
    ActionType.SET_DATES: NodeArity.ITEM,
    ActionType.SET_ESTIMATE: NodeArity.ITEM,
    ActionType.SET_FLAG: NodeArity.ITEM,
    ActionType.SET_VISIBILITY: NodeArity.ITEM,
    ActionType.LINK_ITEM: NodeArity.ITEM,
    ActionType.ARCHIVE_ITEM: NodeArity.ITEM,
    ActionType.ADD_WATCHER: NodeArity.ITEM,
    ActionType.MOVE_TO_PROJECT: NodeArity.ITEM,
    # Outward-facing actions. SET by default because that is what they did
    # before, and because one message about twelve items beats twelve messages.
    ActionType.CREATE_ITEM: NodeArity.SET,
    ActionType.SEND_WEBHOOK: NodeArity.SET,
    ActionType.POST_CHAT: NodeArity.SET,
    ActionType.NOTIFY_USER: NodeArity.SET,
}


#: Actions where BOTH readings are real, so the author chooses:
#:
#: * `create_item` — one triage ticket, or a follow-up per matched item.
#: * `send_webhook` — one batch body, or one POST per item for receivers that
#:   take a single object.
#: * `post_chat` / `notify_user` — a digest, or one per item. A ROLE recipient
#:   resolves against a single item, so it only works at ITEM arity; the editor
#:   forces the mode when one is chosen rather than letting someone build the
#:   version that skip-logs. (`mailintake`'s `send_email` follows the same rule.)
ACTION_ARITY_CONFIGURABLE = frozenset(
    {
        ActionType.CREATE_ITEM,
        ActionType.SEND_WEBHOOK,
        ActionType.POST_CHAT,
        ActionType.NOTIFY_USER,
    }
)


#: Which ports each kind emits by default. FILTER splits the item set; GATE
#: routes by a boolean; TRIGGER, SOURCE and ACTION pass one way — an action
#: returns its input unchanged so chains continue past it.
PORTS_BY_KIND: dict[AutomationNodeKind, tuple[NodePort, ...]] = {
    AutomationNodeKind.TRIGGER: (NodePort.OUT,),
    AutomationNodeKind.SOURCE: (NodePort.OUT,),
    AutomationNodeKind.FILTER: (NodePort.MATCHED, NodePort.UNMATCHED),
    AutomationNodeKind.GATE: (NodePort.TRUE, NodePort.FALSE),
    AutomationNodeKind.ACTION: (NodePort.OUT,),
}


# --- node type keys -----------------------------------------------------------
# The vocabulary, here rather than in the executor: the schemas, the arity table
# and the SPA's catalogue all name these, and a node type spelled differently in
# two of those places is a wire constant with no compiler behind it.

#: RADD-1265: the one open-ended gate — a dotted payload path, an operator and
#: a value. It replaces the retired `gate.event` condition tree as the escape
#: hatch for whatever a named gate does not ask ("release status became
#: released", "the form is the incident form").
TYPE_GATE_PAYLOAD = "gate.payload"
#: RADD-1267: "Project is" — reads the project ref off ANY event that carries
#: one (an item's, a release's, a form's), which is what makes a non-item
#: event narrowable by project at all.
TYPE_GATE_PROJECT = "gate.project"
TYPE_GATE_FIELD_CHANGED = "gate.field_changed"
TYPE_GATE_CHANGED_BY = "gate.changed_by"
TYPE_GATE_STATE_CATEGORY = "gate.state_category"
#: RADD-1498: "Person is in team" — a person named relative to the item (its
#: reporter, its assignee), the event's actor, or an email; true when they are
#: on one of the named teams, directory groups included.
TYPE_GATE_PERSON_IN_TEAM = "gate.person_in_team"
#: RADD-1322: "Entered state category" — reads the transition off the event.
TYPE_GATE_ENTERED_STATE_CATEGORY = "gate.entered_state_category"
TYPE_FILTER_SLQ = "filter.slq"
TYPE_SEARCH_SLQ = "search.slq"
#: The one trigger node type; its `event` param names the trigger (an event type or a
#: trigger kind). Every stored graph starts with one, and templates spell it too.
TYPE_TRIGGER_EVENT = "trigger.event"
ACTION_TYPE_PREFIX = "action."

#: RADD-1329: the two TERMINAL verdict nodes of a validation graph. A submission
#: is refused only because a BLOCK node ran; a WARN node shows its findings and
#: lets the person submit again to create anyway.
TYPE_VERDICT_BLOCK = "verdict.block"
TYPE_VERDICT_WARN = "verdict.warn"


class SearchMode(StrEnum):
    """What a search node does with the packet it was handed.

    REPLACE is the default because the common case is reaching somewhere else
    entirely ("every stale issue"), and silently unioning would make the result
    depend on what the trigger happened to carry."""

    REPLACE = "replace"
    ADD = "add"


class GraphOrientation(StrEnum):
    """Which way the canvas flows. A property of the GRAPH, not of the viewer:
    someone arranges a graph deliberately, and it should open that way for the
    next person rather than re-flowing to their preference."""

    VERTICAL = "vertical"
    HORIZONTAL = "horizontal"


# Guard rails validated on write and re-checked at run time (hand-edited rows).
MAX_GRAPH_NODES = 60
MAX_GRAPH_EDGES = 120
# A graph may hold several triggers (spec 116 revision): "on create OR on a
# schedule" is one automation, not two copies of the same actions. Capped so a
# single graph cannot subscribe to the entire event catalog by accident.
MAX_GRAPH_TRIGGERS = 12
#: Targets one validate trigger may name (spec 119). A graph governing forty
#: forms is a graph nobody can reason about, and the index row count is the
#: product of this and the trigger cap.
MAX_VALIDATION_TARGETS = 25
#: Findings ONE intake verdict may carry, across every governing graph. A person
#: reading a rejected submission can act on a handful; past that it is a wall,
#: and the collection is truncated with the count said out loud.
MAX_INTAKE_FINDINGS = 20


class AutomationEntity(StrEnum):
    RULE = "automation_rule"
    # Entity of the synthetic scheduler event (spec 69) — the module itself.
    AUTOMATION = "automation"


class RunSource(StrEnum):
    """What started a recorded run (RADD-1266). A dry run is never recorded."""

    EVENT = "event"
    SCHEDULE = "schedule"
    MANUAL = "manual"


class RunStatus(StrEnum):
    """How a recorded run ended (RADD-1266); ranked in `runs.status_of`."""

    APPLIED = "applied"  # at least one action resolved and was applied
    NOTHING_TO_DO = "nothing_to_do"  # the walk ran and no action resolved
    REFUSED = "refused"  # a workflow guard or the field registry said no
    FAILED = "failed"  # the walk itself raised


class AutomationEvent(StrEnum):
    CREATED = "automation.created"
    UPDATED = "automation.updated"
    DELETED = "automation.deleted"
    #: RADD-1266: the walk raised. Not a trigger — an automation reacting to
    #: automations failing is the loop guard's nightmare — but audited, so the
    #: ledger says an automation broke even after its run rows are swept.
    RUN_FAILED = "automation.run_failed"
    # Spec 69: the scheduler's synthetic outbox event — payload
    # {rule_id, scheduled_for}. System-emitted by design; the engine
    # special-cases it BEFORE the loop-guard skip. Never subscribable.
    SCHEDULED = "automation.scheduled"


# This module's cursor in the events stream (mirrors webhooks.dispatcher).
CONSUMER_NAME = "automations.engine"


class PlanKind(StrEnum):
    """What a resolved automation action DOES (RADD-898) — the vocabulary the
    engine's planner and applier share."""

    ITEM_UPDATE = "item_update"
    COMMENT = "comment"
    CREATE_ITEM = "create_item"
    # RADD-1267: verbs that are not field writes.
    LINK = "link"
    ARCHIVE = "archive"
    WATCH = "watch"
    MOVE = "move"
    HTTP = "http"
    NOTIFY = "notify"
    SKIP = "skip"


# The system actor: a REAL users row (seeded by migration) that integrations write
# as and author-less automations run as. NOT the loop guard (that is `automated`).
# Instance-admin so authz never blocks it.
SYSTEM_ACTOR_ID = uuid.UUID("00000000-0000-0000-0000-000000a70a70")
SYSTEM_ACTOR_EMAIL = "automation@radd.system"
SYSTEM_ACTOR_NAME = "Automation"

# Literal accepted by the clearing actions (set_assignee/team/cycle/release) to unset.
CLEAR_VALUE = "none"
