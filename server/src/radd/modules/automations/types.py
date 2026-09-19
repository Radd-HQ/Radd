import uuid
from dataclasses import dataclass
from enum import StrEnum

from radd.kernel.specs import OutputField
from radd.schedule import ScheduleKind

# A rule's trigger is an EVENT TYPE string from the workspace event stream
# (spec 58: "item.updated", "comment.created", …, validated against the catalog
# in catalog.py) — or one of these sentinels. MANUAL rules never fire from
# events: they run via POST /automations/{id}/run — the editor's `/`
# quick-action menu lists them, and extensions/MCP can create them, making
# custom quick actions a plain rule. SCHEDULE rules (spec 69) fire from the
# scheduler loop instead of an event; they carry a `schedule` config and must
# have empty event_conditions (there is no event to condition on).
class AutomationTrigger(StrEnum):
    MANUAL = "manual"
    SCHEDULE = "schedule"
    # Spec 119. Fires SYNCHRONOUSLY at intake, against a savepoint-created draft,
    # and its walk applies nothing — it collects FINDINGS. A sentinel like the
    # other two, and for the same reason: no event in the catalog names it, so
    # the engine's outbox consumer can never start a run from it. What it binds
    # to (a form, an issue type, a project) lives in `automation_validations`,
    # indexed off the trigger node's params exactly as a schedule's clock is.
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


class GroupOp(StrEnum):
    """Combinator of an event-condition group (spec 58) — nestable."""

    ALL = "all"
    ANY = "any"
    NONE = "none"


class ConditionSubject(StrEnum):
    """What an event condition inspects — resolved against the triggering event."""

    ACTOR = "actor"  # who caused it: matches user id, email, or name
    CHANGED_FIELD = "changed_field"  # item.updated: names of fields that changed
    OLD_VALUE = "old_value"  # qualifier = field name → the diff's "from"
    NEW_VALUE = "new_value"  # qualifier = field name → the diff's "to"
    STATE_CATEGORY = "state_category"  # item events: the item's state category NOW
    PAYLOAD = "payload"  # qualifier = dotted path into the raw event payload


class ConditionOperator(StrEnum):
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
    # Universal actions (spec 58b) — run with or without a target item.
    CREATE_ITEM = "create_item"
    SEND_WEBHOOK = "send_webhook"
    POST_CHAT = "post_chat"
    NOTIFY_USER = "notify_user"
    SEND_EMAIL = "send_email"  # spec 66 — templated email via radd.smtp


class EmailRecipient(StrEnum):
    """Role values the send_email `to` param may name (spec 66) — anything else
    is a literal address. Roles resolve against the event's TARGET ITEM
    (reporter/assignee = that user's email when active; contact = the spec-62
    mail contact); no item or no resolvable target → the action skip-logs."""

    REPORTER = "reporter"
    ASSIGNEE = "assignee"
    CONTACT = "contact"


class NodeArity(StrEnum):
    """How a node reads its input packet — the axis that used to be implied by
    the action type and could not be chosen (RADD-918).

    There is no LOOP construct in an automation graph and deliberately so: a
    back-edge would break the DAG that `graph.validate` rejects cycles against,
    and a nested-scope executor would make every budget and every report entry
    grow a dimension. In a dataflow model over SETS, "for each" is not control
    flow — it is how a node reads its input, and that is what this names.

    * **SET** — the node runs once and sees the whole packet. A router sends the
      packet down ONE port; an action fires once.
    * **ITEM** — the node runs once per item. A router PARTITIONS the set across
      its ports (each item leaves by the port its own answer names); an action
      fires once per item.

    An action's output is its input either way (chains continue past it), so
    arity on an action has no effect on graph SHAPE — only on how many side
    effects happen. That is what makes this a local property rather than a new
    kind of node.
    """

    SET = "set"
    ITEM = "item"


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


_BOTH = (NodeArity.SET, NodeArity.ITEM)


#: Every action's DEFAULT arity. This table replaces the `ITEM_ACTIONS` frozenset
#: as the source of truth: the frozenset was the law, and now it is the default.
#: The values reproduce the pre-RADD-918 behaviour exactly, which is why no data
#: migration is needed — a stored node with no `arity` param runs as before.
ACTION_ARITY_DEFAULT: dict[ActionType, NodeArity] = {
    # Mutations of one item. Only ITEM is meaningful — there is no canonical
    # item in a set to apply them to.
    ActionType.SET_STATE: NodeArity.ITEM,
    ActionType.SET_PRIORITY: NodeArity.ITEM,
    ActionType.SET_ASSIGNEE: NodeArity.ITEM,
    # Fixed ITEM and NOT in ACTION_ARITY_CONFIGURABLE — there is no legitimate
    # set reading of a round-robin assign, so `_action_arity` gives it
    # options=(ITEM,) and `_check_arity` refuses a hand-edited `arity=set` row.
    # This is the STRONGER of the two per-item forcings: unlike the send_email
    # role (which is set-capable and only forced to item when a role is chosen),
    # this can never be talked into a skip-log on a set at all.
    ActionType.ASSIGN_ROUND_ROBIN: NodeArity.ITEM,
    ActionType.SET_TEAM: NodeArity.ITEM,
    ActionType.ADD_LABEL: NodeArity.ITEM,
    ActionType.REMOVE_LABEL: NodeArity.ITEM,
    ActionType.SET_CYCLE: NodeArity.ITEM,
    ActionType.SET_RELEASE: NodeArity.ITEM,
    ActionType.SET_CUSTOM_FIELD: NodeArity.ITEM,
    ActionType.ADD_COMMENT: NodeArity.ITEM,
    # Outward-facing actions. SET by default because that is what they did
    # before, and because one message about twelve items beats twelve messages.
    ActionType.CREATE_ITEM: NodeArity.SET,
    ActionType.SEND_WEBHOOK: NodeArity.SET,
    ActionType.POST_CHAT: NodeArity.SET,
    ActionType.NOTIFY_USER: NodeArity.SET,
    ActionType.SEND_EMAIL: NodeArity.SET,
}


#: Actions where BOTH readings are real, so the author chooses:
#:
#: * `create_item` — one triage ticket, or a follow-up per matched item.
#: * `send_email` — a digest to a fixed address, or one mail per item. The
#:   ROLE recipients (reporter/assignee/contact) resolve against a single item,
#:   so they only work at ITEM arity; the editor forces the mode when one is
#:   chosen rather than letting someone build the version that skip-logs.
#: * `send_webhook` — one batch body, or one POST per item for receivers that
#:   take a single object.
#: * `post_chat` / `notify_user` — a digest, or one per item.
ACTION_ARITY_CONFIGURABLE = frozenset(
    {
        ActionType.CREATE_ITEM,
        ActionType.SEND_WEBHOOK,
        ActionType.POST_CHAT,
        ActionType.NOTIFY_USER,
        ActionType.SEND_EMAIL,
    }
)


# ActionTypes whose DEFAULT needs the event's target item. Derived rather than
# declared, so it cannot drift from the table above; still exported because the
# engine, the schemas and several tests read it by name.
ITEM_ACTIONS = frozenset(
    action for action, arity in ACTION_ARITY_DEFAULT.items() if arity is NodeArity.ITEM
)


# The complement — actions that default to running once, with or without a
# target item.
UNIVERSAL_ACTIONS = frozenset(ActionType) - ITEM_ACTIONS


class AutomationNodeKind(StrEnum):
    """The node kinds of an automation graph (spec 116).

    FILTER and GATE stay apart even though RADD-918 gave them one implementation,
    because they answer different questions on the canvas: a filter is a
    predicate over EACH ITEM answering with a SUBSET, a gate is a question
    answered ONCE for the packet. "Changed by someone in QA" is not a property
    any single item has. Sharing machinery is not the same as sharing a concept.

    SOURCE is the fifth (RADD-919). Every other kind can only narrow what the
    trigger handed it, so an automation could never reach an item the event did
    not name — "when this ships, find everything blocked by it" was inexpressible
    with any arrangement of filters. A source PRODUCES items, which is a
    different verb from every other node here and so a different kind.
    """

    TRIGGER = "trigger"
    SOURCE = "source"
    FILTER = "filter"
    GATE = "gate"
    ACTION = "action"


class NodePort(StrEnum):
    """Named outputs. A node's kind fixes which of these it has by default
    (PORTS_BY_KIND); a TYPE may name its own (BUILTIN_PORTS, or a contributed
    spec's `ports_for`). An edge naming a port the source cannot emit is
    rejected on write."""

    OUT = "out"
    MATCHED = "matched"
    UNMATCHED = "unmatched"
    TRUE = "true"
    FALSE = "false"
    #: What `create_item` MADE, as opposed to what it was given. Without it the
    #: new issue was unreachable — the action emitted its input, so nothing
    #: downstream could assign, label or comment on what had just been created.
    CREATED = "created"


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

TYPE_GATE_EVENT = "gate.event"  # pre-revision; still executed, no longer offered
TYPE_GATE_FIELD_CHANGED = "gate.field_changed"
TYPE_GATE_CHANGED_BY = "gate.changed_by"
TYPE_GATE_STATE_CATEGORY = "gate.state_category"
#: RADD-1248: "Comment is…" (root/reply, public/internal) and "Page is in
#: space…" — the two questions a page or thread automation asks first.
TYPE_GATE_COMMENT = "gate.comment"
TYPE_GATE_PAGE_SPACE = "gate.page_space"
TYPE_FILTER_SLQ = "filter.slq"
TYPE_SEARCH_SLQ = "search.slq"
ACTION_TYPE_PREFIX = "action."

#: Gates that read the triggering EVENT — its diff, its actor, its condition
#: tree. A validation run has no event: `validate_facts` builds a synthetic
#: packet with a system actor and no changes, so each of these evaluates against
#: something that never happened and answers with a constant. Refused on write
#: under a validate trigger for the reason the schedule check exists: a gate
#: that can only ever be false is a branch nobody's graph will take, and it
#: looks configured. `gate.state_category` is NOT here — the draft has a state,
#: and asking about it is a real question.
EVENT_GATE_TYPES: frozenset[str] = frozenset(
    {TYPE_GATE_EVENT, TYPE_GATE_FIELD_CHANGED, TYPE_GATE_CHANGED_BY, TYPE_GATE_COMMENT, TYPE_GATE_PAGE_SPACE}
)

#: Spec 119: reaching this node records a FINDING against the draft being
#: validated, and passes the packet on unchanged so several checks can chain off
#: one branch.
#:
#: An ACTION kind rather than a sixth `AutomationNodeKind`, deliberately. Its
#: port behaviour is byte-identical to every other action's — one `out` that
#: carries its input through — so a new kind would buy a `PORTS_BY_KIND` row, a
#: `BUILTIN_ARITY` row, a SPA `NodeKind` member and a canvas visual, all to
#: express a difference that lives entirely in what the node DOES. That is what
#: `type` is for. On an ordinary event walk it is a no-op that passes through:
#: nothing is collecting findings there, which is the honest answer rather than
#: an error about a node someone wired in the wrong graph.
TYPE_VALIDATION_FAIL = "validation.fail"


#: Ports a built-in node TYPE emits, when they are not just its kind's. Only
#: `create_item` needs an entry today; the table exists because `ports_of` has
#: to consult one place whether the type is built-in or contributed.
BUILTIN_PORTS: dict[str, tuple[NodePort, ...]] = {
    f"{ACTION_TYPE_PREFIX}{ActionType.CREATE_ITEM.value}": (NodePort.OUT, NodePort.CREATED),
}


#: Named values a built-in node TYPE produces (spec 120), mirroring
#: `BUILTIN_PORTS` — one table `nodes.outputs_of` consults whether the type is
#: built-in or contributed.
#:
#: `create_item` is the only built-in producer, and it is the one that makes
#: "file a follow-up, then say so on the original" expressible: before this the
#: new issue's key existed only inside the engine, so a comment on the item that
#: caused it could not name what had just been filed.
#:
#: The TRIGGER deliberately produces nothing. The event it carries is already
#: the `{{event_type}}`/`{{actor.*}}`/`{{payload.*}}` root vocabulary, and
#: giving it a bag entry too would be a second way to say the same thing — with
#: the second one silently unavailable on the manual and schedule triggers.
BUILTIN_OUTPUTS: dict[str, tuple[OutputField, ...]] = {
    f"{ACTION_TYPE_PREFIX}{ActionType.CREATE_ITEM.value}": (
        OutputField(name="key", label="Key", description="The new issue's key, e.g. TD-42."),
        OutputField(name="id", label="Id", description="Its uuid."),
        OutputField(name="url", label="URL", description="A link to it."),
    ),
}


def _action_arity(action: ActionType) -> ArityRule:
    default = ACTION_ARITY_DEFAULT[action]
    return ArityRule(default, _BOTH if action in ACTION_ARITY_CONFIGURABLE else (default,))


#: Arity per built-in node type. Gates read the EVENT (`EventFacts`), never the
#: items, so per-item would be N identical answers — they are fixed at SET. A
#: filter is the original per-item partition and is fixed at ITEM. A source
#: produces the set rather than reading it, so it runs once.
BUILTIN_ARITY: dict[str, ArityRule] = {
    TYPE_FILTER_SLQ: ArityRule(NodeArity.ITEM, (NodeArity.ITEM,)),
    # Fixed SET: one check, one finding. A validation walk carries exactly one
    # draft, so ITEM would say the same thing with a loop around it — and would
    # invite a per-item reading of a node whose subject is the submission. It
    # still refuses to fire on an EMPTY packet (see `executor._run_action`),
    # which is what makes `filter → matched → check` mean "only when this
    # applies" rather than "always".
    TYPE_VALIDATION_FAIL: ArityRule(NodeArity.SET, (NodeArity.SET,)),
    TYPE_SEARCH_SLQ: ArityRule(NodeArity.SET, (NodeArity.SET,)),
    TYPE_GATE_EVENT: ArityRule(NodeArity.SET, (NodeArity.SET,)),
    TYPE_GATE_FIELD_CHANGED: ArityRule(NodeArity.SET, (NodeArity.SET,)),
    TYPE_GATE_CHANGED_BY: ArityRule(NodeArity.SET, (NodeArity.SET,)),
    TYPE_GATE_STATE_CATEGORY: ArityRule(NodeArity.SET, (NodeArity.SET,)),
    TYPE_GATE_COMMENT: ArityRule(NodeArity.SET, (NodeArity.SET,)),
    TYPE_GATE_PAGE_SPACE: ArityRule(NodeArity.SET, (NodeArity.SET,)),
    **{f"{ACTION_TYPE_PREFIX}{action.value}": _action_arity(action) for action in ActionType},
}


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


# Guard rails for a stored graph, mirroring conditions.MAX_DEPTH/MAX_NODES:
# validated on write and enforced again at run time, so a hand-crafted DB row
# cannot wedge the engine.
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


class AutomationEvent(StrEnum):
    CREATED = "automation.created"
    UPDATED = "automation.updated"
    DELETED = "automation.deleted"
    # Spec 69: the scheduler's synthetic outbox event — payload
    # {rule_id, scheduled_for}. System-emitted by design; the engine
    # special-cases it BEFORE the loop-guard skip. Never subscribable.
    SCHEDULED = "automation.scheduled"


# This module's cursor in the events stream (mirrors webhooks.dispatcher).
CONSUMER_NAME = "automations.engine"

# The system actor that owns every engine-applied mutation. It is a REAL users row
# (seeded by this module's migration so the comments.author_id FK resolves) AND the
# loop guard: the engine skips any item event whose actor_id is this id, so an action
# that re-triggers its own rule cannot spin. Instance-admin so authz never blocks it.
class PlanKind(StrEnum):
    """What a resolved automation action DOES (RADD-898) — the vocabulary the
    engine's planner and applier share. Was a comment on `_Plan.kind`; a typo in
    one branch was invisible."""

    ITEM_UPDATE = "item_update"
    COMMENT = "comment"
    CREATE_ITEM = "create_item"
    HTTP = "http"
    NOTIFY = "notify"
    EMAIL = "email"
    SKIP = "skip"


SYSTEM_ACTOR_ID = uuid.UUID("00000000-0000-0000-0000-000000a70a70")
SYSTEM_ACTOR_EMAIL = "automation@radd.system"
SYSTEM_ACTOR_NAME = "Automation"

# Literal accepted by the clearing actions (set_assignee/team/cycle/release) to unset.
CLEAR_VALUE = "none"
