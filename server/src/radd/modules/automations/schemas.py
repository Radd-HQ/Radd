import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from radd.modules.comments.types import CommentVisibility
from radd.modules.items.enums import ItemKind, Priority

from radd import schedule as schedule_math

from . import catalog, conditions
from .templating import TOKEN_RE
from .types import (
    MAX_GRAPH_EDGES,
    MAX_GRAPH_NODES,
    ActionType,
    AutomationNodeKind,
    AutomationTrigger,
    GraphOrientation,
    ConditionOperator,
    ConditionSubject,
    GroupOp,
    NodeArity,
    NodePort,
    ScheduleKind,
)
from radd.apitypes import UtcDatetime


# --- event-condition tree (spec 58) ---

_VALUELESS = {ConditionOperator.IS_SET, ConditionOperator.NOT_SET}
_QUALIFIED = {
    ConditionSubject.OLD_VALUE,
    ConditionSubject.NEW_VALUE,
    ConditionSubject.PAYLOAD,
}


class EventCondition(BaseModel):
    subject: ConditionSubject
    # Field name (old/new value) or dotted payload path — required by those subjects.
    qualifier: str | None = Field(default=None, max_length=200)
    operator: ConditionOperator
    # Scalar for most operators; a list for in/not_in.
    value: str | int | float | bool | list[str] | None = None

    @model_validator(mode="after")
    def _check_shape(self) -> "EventCondition":
        if self.subject in _QUALIFIED and not (self.qualifier or "").strip():
            raise ValueError(f"subject {self.subject.value!r} needs a qualifier")
        if self.operator not in _VALUELESS and self.value in (None, ""):
            raise ValueError(f"operator {self.operator.value!r} needs a value")
        return self


class ConditionGroup(BaseModel):
    op: GroupOp = GroupOp.ALL
    conditions: list["ConditionGroup | EventCondition"] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_size(self) -> "ConditionGroup":
        tree = self.model_dump(mode="json")
        if conditions._count_nodes(tree) > conditions.MAX_NODES:
            raise ValueError(f"condition tree exceeds {conditions.MAX_NODES} nodes")
        if conditions.tree_depth(tree) > conditions.MAX_DEPTH:
            raise ValueError(f"condition tree exceeds depth {conditions.MAX_DEPTH}")
        return self

# --- action params + discriminated union (validated on rule write) ---


class SetStateParams(BaseModel):
    state: str = Field(min_length=1)  # state name within the item's project


#: Value params that may carry a `{{token}}` instead of a literal (spec 120).
#: Typed as strings with this check rather than as the enum, because the whole
#: point is that the value can be produced at RUN time — `Priority` on the wire
#: would refuse `{{triage.priority}}` before it ever had a chance to render.
#: What the token renders to is still measured against the enum, in the planner,
#: where the failure is a recorded skip naming the vocabulary.
def templated_enum(value: str, allowed: set[str], label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{label} is required")
    if TOKEN_RE.search(text) or text in allowed:
        return text
    raise ValueError(
        f"{text!r} is not a {label} — one of {', '.join(sorted(allowed))}, "
        f"or a {{{{token}}}} that produces one"
    )


class SetPriorityParams(BaseModel):
    #: A `Priority` value, or a template that renders to one.
    priority: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _check_priority(self) -> "SetPriorityParams":
        self.priority = templated_enum(self.priority, set(Priority), "priority")
        return self


class SetAssigneeParams(BaseModel):
    assignee: str = Field(min_length=1)  # user email, or the literal "none" to clear


class AssignRoundRobinParams(BaseModel):
    # Team NAME whose members the assignment rotates through (RADD-1044). Resolved
    # at apply time like every other named target, so it keeps working when the
    # team is recreated; an unresolvable name skip-logs rather than failing.
    team: str = Field(min_length=1)


class SetTeamParams(BaseModel):
    team: str = Field(min_length=1)  # team name, or "none" to clear


class AddLabelParams(BaseModel):
    label: str = Field(min_length=1)


class RemoveLabelParams(BaseModel):
    label: str = Field(min_length=1)


class SetCycleParams(BaseModel):
    cycle: str = Field(min_length=1)  # cycle name, or "none" to clear


class SetReleaseParams(BaseModel):
    release: str = Field(min_length=1)  # release version, or "none" to clear


class SetCustomFieldParams(BaseModel):
    key: str = Field(min_length=1)
    value: Any = None


class AddCommentParams(BaseModel):
    body: str = Field(min_length=1)
    visibility: CommentVisibility = CommentVisibility.PUBLIC


# --- universal actions (spec 58b) — `{{token}}` templates render per event ---


class CreateItemParams(BaseModel):
    """Everything you can set on a new issue (spec 116).

    Was four fields — project, title, description, priority — which meant an
    automation could only ever file a stub someone then had to finish by hand.
    Every name here resolves at APPLY time (state name, assignee email, cycle
    name, parent key), not on write, because the target project's vocabulary can
    change between saving the automation and running it; an unresolvable name
    skip-logs with the name in the message rather than failing the run.

    Every text field is a `{{token}}` template. `custom_fields` values are too,
    when they are strings — a select's option or a text field's content is
    exactly where "from {{item.key}}" belongs.
    """

    project: str = Field(min_length=1)  # project KEY
    title: str = Field(min_length=1, max_length=500)  # template
    description: str = Field(default="", max_length=10_000)  # template
    #: A `Priority` value, or a template that renders to one (spec 120).
    priority: str | None = Field(default=None, max_length=200)
    #: Issue type NAME (spec 51); None = the project's default.
    type: str | None = Field(default=None, max_length=100)
    #: epic | issue | subtask. A subtask needs `parent`; an epic forbids one.
    kind: ItemKind | None = None
    #: Workflow state NAME; None = the project's default (its first state).
    state: str | None = Field(default=None, max_length=100)
    #: User EMAIL, or "none". Names resolve per project at apply time.
    assignee: str | None = Field(default=None, max_length=320)
    #: Who it is filed BY. Defaults to the automation's acting identity, which is
    #: the author unless the action names someone else — so the reporter matches
    #: who the change is attributed to rather than being a second, silent choice.
    reporter: str | None = Field(default=None, max_length=320)
    team: str | None = Field(default=None, max_length=200)
    cycle: str | None = Field(default=None, max_length=200)
    release: str | None = Field(default=None, max_length=100)
    #: Parent item KEY (TD-42). Required for a subtask.
    parent: str | None = Field(default=None, max_length=64)
    labels: list[str] = Field(default_factory=list, max_length=50)
    flagged: bool = False
    estimate_points: float | None = Field(default=None, ge=0, le=999)
    #: ISO dates, or a relative literal the SLQ vocabulary already knows
    #: ("today", "today+3d") — the same words the schedule filter uses, so one
    #: date language covers the whole feature.
    start_date: str | None = Field(default=None, max_length=32)
    target_date: str | None = Field(default=None, max_length=32)
    #: Custom fields by registry key. Validated against the target project's
    #: definitions at apply time by the items service, exactly as a human create
    #: would be — this does not get its own second validator.
    custom_fields: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_priority(self) -> "CreateItemParams":
        if self.priority is not None:
            self.priority = templated_enum(self.priority, set(Priority), "priority")
        return self


class SendWebhookParams(BaseModel):
    url: str = Field(min_length=1, max_length=1000, pattern=r"^https?://")
    # Optional HMAC-SHA256 of the body, hex in X-Radd-Signature.
    secret: str = Field(default="", max_length=200)


class PostChatParams(BaseModel):
    # A Google Chat / Slack-style incoming webhook: POSTs {"text": message}.
    webhook_url: str = Field(min_length=1, max_length=1000, pattern=r"^https?://")
    message: str = Field(min_length=1, max_length=4000)  # template


class NotifyUserParams(BaseModel):
    #: A user email, or the role `reporter`/`assignee` — resolved against the
    #: item at apply time, which only means anything at per-item arity. Roles
    #: were added by RADD-918: "notify the assignee" previously had to name a
    #: person, so it could not be written once for a whole project.
    user: str = Field(min_length=1)
    message: str = Field(min_length=1, max_length=1000)  # template


class SendEmailParams(BaseModel):
    # A literal address, or an `EmailRecipient` role: reporter/assignee/contact
    # (resolved against the event's target item at apply time, spec 66).
    to: str = Field(min_length=1, max_length=320)
    subject: str = Field(min_length=1, max_length=500)  # template
    body: str = Field(min_length=1, max_length=10_000)  # template


class SetStateAction(BaseModel):
    type: Literal[ActionType.SET_STATE]
    params: SetStateParams


class SetPriorityAction(BaseModel):
    type: Literal[ActionType.SET_PRIORITY]
    params: SetPriorityParams


class SetAssigneeAction(BaseModel):
    type: Literal[ActionType.SET_ASSIGNEE]
    params: SetAssigneeParams


class AssignRoundRobinAction(BaseModel):
    type: Literal[ActionType.ASSIGN_ROUND_ROBIN]
    params: AssignRoundRobinParams


class SetTeamAction(BaseModel):
    type: Literal[ActionType.SET_TEAM]
    params: SetTeamParams


class AddLabelAction(BaseModel):
    type: Literal[ActionType.ADD_LABEL]
    params: AddLabelParams


class RemoveLabelAction(BaseModel):
    type: Literal[ActionType.REMOVE_LABEL]
    params: RemoveLabelParams


class SetCycleAction(BaseModel):
    type: Literal[ActionType.SET_CYCLE]
    params: SetCycleParams


class SetReleaseAction(BaseModel):
    type: Literal[ActionType.SET_RELEASE]
    params: SetReleaseParams


class SetCustomFieldAction(BaseModel):
    type: Literal[ActionType.SET_CUSTOM_FIELD]
    params: SetCustomFieldParams


class AddCommentAction(BaseModel):
    type: Literal[ActionType.ADD_COMMENT]
    params: AddCommentParams


class CreateItemAction(BaseModel):
    type: Literal[ActionType.CREATE_ITEM]
    params: CreateItemParams


class SendWebhookAction(BaseModel):
    type: Literal[ActionType.SEND_WEBHOOK]
    params: SendWebhookParams


class PostChatAction(BaseModel):
    type: Literal[ActionType.POST_CHAT]
    params: PostChatParams


class NotifyUserAction(BaseModel):
    type: Literal[ActionType.NOTIFY_USER]
    params: NotifyUserParams


class SendEmailAction(BaseModel):
    type: Literal[ActionType.SEND_EMAIL]
    params: SendEmailParams


Action = Annotated[
    SetStateAction
    | SetPriorityAction
    | SetAssigneeAction
    | AssignRoundRobinAction
    | SetTeamAction
    | AddLabelAction
    | RemoveLabelAction
    | SetCycleAction
    | SetReleaseAction
    | SetCustomFieldAction
    | AddCommentAction
    | CreateItemAction
    | SendWebhookAction
    | PostChatAction
    | NotifyUserAction
    | SendEmailAction,
    Field(discriminator="type"),
]

#: The union as a standalone validator. Before spec 116 an action's params were
#: type-checked because `RuleCreate.actions` was `list[Action]`; a graph node's
#: `params` is an untyped envelope, so the service revalidates each ACTION node
#: through this. Without it a typo'd param would be stored happily and fail at
#: 3am — the check moved, it did not go away. Phase 2 generalises this to a
#: `params_schema` per node type, which is how a plugin's node gets the same.
ActionAdapter: TypeAdapter[Action] = TypeAdapter(Action)


# --- schedule config (spec 69) — the `schedule` JSONB of scheduled rules ---


class ScheduleConfig(BaseModel):
    """A stored schedule: interval every N minutes, daily/weekly/monthly at a
    wall-clock time, or a cron expression. Times run on the instance clock
    (`settings.scheduler_tz`).

    The SHAPE rules live in `radd.schedule` (RADD-909/910) — backups store the
    same vocabulary, and the two copies of these checks had already drifted
    apart before two more kinds were added to both."""

    kind: ScheduleKind
    minutes: int | None = None
    time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    weekdays: list[int] | None = None
    #: Day of the month for a monthly schedule; clamped to the month's last day.
    day: int | None = Field(default=None, ge=1, le=31)
    #: Five-field cron expression.
    expression: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _check_shape(self) -> "ScheduleConfig":
        schedule_math.validate_config(self.model_dump(exclude_none=True))
        return self


class SchedulePreviewRequest(BaseModel):
    """A candidate schedule, not necessarily a valid one — the point of the
    endpoint is to say WHY when it is not, so this deliberately does not reuse
    `ScheduleConfig` (whose validator would 422 with pydantic's wrapping before
    the handler could phrase the answer)."""

    kind: str
    minutes: int | None = None
    time: str | None = Field(default=None, max_length=10)
    weekdays: list[int] | None = None
    day: int | None = None
    expression: str | None = Field(default=None, max_length=200)


class SchedulePreviewRead(BaseModel):
    """The next few occurrences, or the reason there are none."""

    timezone: str
    next_runs: list[UtcDatetime] = []
    error: str | None = None



# --- rule CRUD schemas ---


def known_trigger(value: str) -> str:
    """Public since spec 116: the trigger moved from a rule COLUMN with a field
    validator to the trigger node's `params.event`, which this envelope does not
    type — so the service calls this while validating the graph. Dropping the
    check would make a typo'd event a silently dead automation rather than a 422."""
    if value not in set(AutomationTrigger) and value not in catalog.TRIGGERS:
        raise ValueError(f"unknown trigger {value!r} — see GET /automations/catalog")
    return value


class NodeIn(BaseModel):
    """One node of the graph (spec 116).

    `params` is deliberately untyped here: what a node accepts is the business of
    its TYPE, not of this envelope — a trigger takes `{event, schedule}`, a filter
    `{slq}`, a gate `{conditions}`, an action whatever its action takes. Phase 2
    makes that a `params_schema` on the node registry so a plugin's node validates
    the same way; until then the service validates the params it knows about
    (a filter's SLQ is compiled on write) and the rest are checked when planned.
    """

    id: str = Field(min_length=1, max_length=64)
    kind: AutomationNodeKind
    type: str = Field(min_length=1, max_length=100)
    params: dict[str, Any] = Field(default_factory=dict)
    #: What downstream tokens call this node (spec 120) — the left half of
    #: `{{triage.priority}}`. Typed loosely HERE and checked by the service,
    #: because the interesting rules (unique in this graph, not a reserved
    #: template word) are graph-wide facts a per-field validator cannot see, and
    #: splitting them across two places is how the two disagree.
    name: str = Field(default="", max_length=30)
    # Canvas coordinates. Optional and ignored by the engine — `graph.parse`
    # never reads them, so a graph laid out by hand and one laid out
    # automatically execute identically. Absent means "no one has placed this
    # node": the editor lays those out from the topology instead, which is what
    # lets every migrated automation open on the canvas without a data migration.
    x: float | None = None
    y: float | None = None


class EdgeIn(BaseModel):
    source: str = Field(min_length=1, max_length=64)
    #: Free-form, checked against the SOURCE NODE's real ports while validating
    #: the graph — not against `NodePort`. Typing it as the enum here made the
    #: five built-in names the only wireable ports, which silently disabled every
    #: contributed node with dynamic outputs (RADD-918).
    port: str = Field(default=NodePort.OUT.value, min_length=1, max_length=64)
    target: str = Field(min_length=1, max_length=64)


class RuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    enabled: bool = True
    position: int = 0
    #: Which way the canvas flows. Stored per automation, not per viewer.
    orientation: GraphOrientation = GraphOrientation.VERTICAL
    # The graph. `trigger` and `schedule` are NOT accepted here — they are
    # denormalised from the trigger node by the service, so there is exactly one
    # place that says which event starts this automation. Taking both would let a
    # caller disagree with itself.
    nodes: list[NodeIn] = Field(min_length=1, max_length=MAX_GRAPH_NODES)
    edges: list[EdgeIn] = Field(default_factory=list, max_length=MAX_GRAPH_EDGES)


class RuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    enabled: bool | None = None
    position: int | None = None
    orientation: GraphOrientation | None = None
    # Replaced whole or not at all — see update_rule. Sending one without the
    # other keeps the stored counterpart, and the pair is re-validated together.
    nodes: list[NodeIn] | None = Field(default=None, min_length=1, max_length=MAX_GRAPH_NODES)
    edges: list[EdgeIn] | None = Field(default=None, max_length=MAX_GRAPH_EDGES)


class RuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    enabled: bool
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    position: int
    orientation: GraphOrientation = GraphOrientation.VERTICAL
    # Spec 69: the stored schedule config + the scheduler's bookkeeping (the
    # next/last-run stamps live in automation_schedule_state — the service
    # hydrates them via `rule_reads`; None for event/manual rules).
    #: One entry per TRIGGER node, with its scheduler stamps. A list rather than
    #: the old scalar `schedule`/`next_run_at`/`last_run_at`, because a graph may
    #: hold several triggers and a scalar could only describe one of them —
    #: silently, which is the worst way to be wrong about when something runs.
    triggers: list["TriggerRead"] = Field(default_factory=list)
    created_at: UtcDatetime
    updated_at: UtcDatetime


class TriggerRead(BaseModel):
    """A trigger node projected for the editor: what fires it, and when next."""

    model_config = ConfigDict(from_attributes=True)

    node_id: str
    event_type: str
    schedule: dict[str, Any] | None = None
    next_run_at: UtcDatetime | None = None
    last_run_at: UtcDatetime | None = None


# --- GET /automations/catalog — builder metadata for the UI ---


class TriggerInfo(BaseModel):
    event_type: str
    label: str
    group: str
    item_scoped: bool
    has_changes: bool


class SubjectInfo(BaseModel):
    key: ConditionSubject
    label: str
    needs_qualifier: bool
    qualifier_hint: str
    requires_changes: bool


class OperatorInfo(BaseModel):
    key: ConditionOperator
    label: str
    needs_value: bool
    list_value: bool


class ScheduleKindInfo(BaseModel):
    key: ScheduleKind
    label: str


class ContributedNodeInfo(BaseModel):
    """A node type from the kernel registry (spec 116 phase 2).

    Served rather than baked into the SPA for the same reason the trigger
    catalogue is: what nodes exist is a function of which plugins are INSTALLED,
    so a hardcoded palette would offer the AI classifier on an instance without
    the AI module and miss anything a plugin adds."""

    key: str
    kind: str
    label: str
    description: str = ""
    group: str = "Other"
    params_schema: dict[str, Any] = Field(default_factory=dict)
    #: The node's FIXED ports, when its outputs do not depend on its params
    #: (RADD-1064). Empty means they DO — the editor computes those itself as the
    #: form is edited, because an AI classifier's ports are the answers someone
    #: is still typing. The distinction is the whole value of the field: without
    #: it a client cannot tell a real port set from one node's starting shape,
    #: and `ai.validate` drew a gate's TRUE/FALSE handles instead of its own.
    ports: list[str] = Field(default_factory=list)
    #: Ports for the node's DEFAULT params. The editor recomputes them locally as
    #: the form is edited (an AI classifier's ports are its answers), so this is
    #: the starting shape, not the final word.
    default_ports: list[str] = Field(default_factory=list)
    #: The node's FIXED named outputs (spec 120), on exactly the terms `ports`
    #: is fixed: empty means they depend on the params — `ai.generate`'s outputs
    #: ARE the fields someone is still typing — and the editor computes those
    #: locally as the form changes.
    outputs: list["OutputFieldInfo"] = Field(default_factory=list)
    needs_items: bool = True
    permission: str = ""


class OutputFieldInfo(BaseModel):
    """One value a node produces, addressable as `{{<node name>.<name>}}`."""

    name: str
    label: str = ""
    kind: str = "text"
    #: The values an ENUM output may take — what the editor offers, and what the
    #: write path measures a comparison against.
    choices: list[str] = Field(default_factory=list)
    description: str = ""


class NodeOutputsInfo(BaseModel):
    """What one BUILT-IN node type produces (spec 120).

    A table beside `node_arity` rather than a field on the node, for the same
    reason that one exists: the editor must answer "what tokens may I offer for
    this node" for built-in and contributed types alike, and a second copy of
    `action.create_item → key, id, url` in TypeScript is a copy that drifts."""

    type: str
    outputs: list[OutputFieldInfo] = Field(default_factory=list)


class NodeArityInfo(BaseModel):
    """How one node type may read its packet (RADD-918).

    `options` of length one means fixed, and the editor shows no control — a
    toggle with a single setting is noise that teaches nothing."""

    type: str
    default: NodeArity
    options: list[NodeArity]


class TemplateTokenInfo(BaseModel):
    token: str
    description: str
    needs_item: bool = False


class PayloadPathInfo(BaseModel):
    """One addressable path into an event payload, with values really seen at it.
    The string is what `{{payload.<path>}}` and the payload condition take."""

    path: str
    examples: list[str] = Field(default_factory=list)
    #: Inside a list — a template reading it may render several values, joined.
    repeated: bool = False


class EventSampleRead(BaseModel):
    """What an event type actually carries, from the outbox (RADD-921).

    Sampled from REAL events. A hand-written example per type would be a second
    copy of a shape defined in twenty modules' `emit` calls, and it would drift
    silently — the failure mode here is a payload that looks right and isn't."""

    event_type: str
    #: How many recent events the paths were derived from. 0 = this type has
    #: never fired here, which the UI says rather than inventing a shape.
    sampled: int
    paths: list[PayloadPathInfo] = Field(default_factory=list)
    #: Field names seen in `changes` diffs — what "field changed" can test. The
    #: picker otherwise offers every custom-field key, including ones the diff
    #: never names: a condition that can only ever be false.
    changed_fields: list[str] = Field(default_factory=list)
    #: One whole payload, verbatim, for when the flattened paths are not enough.
    example: dict[str, Any] | None = None
    #: Entity types this event is ABOUT (RADD-923). Each appears in the payload
    #: as a canonical ref under its own key, written by the kernel — so
    #: `subjects: ["item"]` means `{{payload.item.key}}` resolves whether or not
    #: this instance has ever fired the event.
    subjects: list[str] = Field(default_factory=list)
    #: The event's OWN declared shape, beyond the refs. Present even when
    #: `sampled` is 0, which is the case the samples panel could not answer:
    #: sampling describes what HAS happened, declaration describes what WILL.
    declared_schema: dict[str, Any] = Field(default_factory=dict)


class CatalogRead(BaseModel):
    triggers: list[TriggerInfo]
    subjects: list[SubjectInfo]
    operators: list[OperatorInfo]
    manual_trigger: str = AutomationTrigger.MANUAL.value
    # Spec 69: the "On a schedule" sentinel + the schedule kinds the builder offers.
    schedule_trigger: str = AutomationTrigger.SCHEDULE.value
    schedule_kinds: list[ScheduleKindInfo] = []
    #: Node types contributed through the kernel registry.
    contributed_nodes: list[ContributedNodeInfo] = []
    #: How each node type reads its packet, built-in and contributed alike —
    #: one table so the editor's default cannot disagree with the engine's.
    node_arity: list[NodeArityInfo] = []
    #: What each BUILT-IN node type produces (spec 120). Contributed types carry
    #: theirs on `contributed_nodes[].outputs`, static-or-dynamic exactly as
    #: their ports are.
    node_outputs: list[NodeOutputsInfo] = []
    #: Whether the CALLER may make an action run as someone else. The editor
    #: hides the field entirely when false — an affordance that is refused on
    #: save is worse than one that is absent.
    can_act_as: bool = False
    #: `{{token}}` substitutions available in action text fields.
    tokens: list[TemplateTokenInfo] = []


# --- /test dry-run preview ---


class RuleTestRequest(BaseModel):
    #: The item to run against. OPTIONAL since RADD-921: a graph whose items come
    #: from a search node or a schedule trigger has no seed, and demanding one
    #: made exactly those graphs — the ones with the most to check — the ones
    #: that could not be dry-run.
    item_id: uuid.UUID | None = None
    #: Which trigger to start from. A graph may hold several entry points and
    #: they do different things; "the first one" is not a well-formed answer.
    trigger_node_id: str | None = Field(default=None, max_length=64)


class PortResult(BaseModel):
    """What left one port of one node."""

    port: str
    count: int
    #: Item keys, capped. The count is exact; this is a recognisable sample.
    sample: list[str] = Field(default_factory=list)
    #: False = the node did not emit this port AT ALL — a gate's untaken branch.
    #: Distinct from a port that emitted zero items, which is a filter matching
    #: nothing, and the two mean opposite things downstream.
    taken: bool = True


class ProducedVar(BaseModel):
    """One value a node produced on a dry run, with the token that reads it.

    The TOKEN rather than just the field name, because that is the thing someone
    copies: `{{triage.priority}} = high` answers "what do I write downstream" in
    one line, and a bare `priority = high` answers it only for someone who
    already knows the addressing rule."""

    token: str
    name: str
    value: str


class NodeResult(BaseModel):
    """One node's dry run: what arrived, and what left by each port."""

    node_id: str
    kind: str
    type: str
    #: What downstream tokens call this node (spec 120), "" when unnamed.
    name: str = ""
    #: What it PRODUCED. Present even when the node has no name — an unnamed
    #: producer is exactly the mistake this makes visible, and hiding its output
    #: would leave "why does my token not resolve" unanswerable from the report.
    produced: list[ProducedVar] = Field(default_factory=list)
    #: False = never reached — detached from the trigger, or the budget ran out
    #: before the walk got here.
    ran: bool = True
    incoming: int = 0
    incoming_sample: list[str] = Field(default_factory=list)
    ports: list[PortResult] = Field(default_factory=list)


class ActionPreview(BaseModel):
    type: ActionType
    params: dict[str, Any]
    resolves: bool  # would the action's target(s) resolve at apply time?
    detail: str
    #: Which node planned it, and against which item. A graph runs the same
    #: action type from several nodes and, at per-item arity, once per item — a
    #: flat list of "would apply" could not say which was which.
    node_id: str = ""
    item_key: str = ""
    #: `{{token}}` -> what it rendered to on this invocation (spec 120). Only
    #: params that CARRIED a token appear: repeating every literal beside them
    #: would bury the one line someone is looking for. When `resolves` is false
    #: this is what the skip in `detail` is about.
    resolved: dict[str, str] = Field(default_factory=dict)


class RuleTestResult(BaseModel):
    rule_id: uuid.UUID
    #: None when the run had no seed item (a schedule or search-fed graph).
    item_id: uuid.UUID | None = None
    matched: bool
    would_apply: list[ActionPreview]
    #: Which trigger the run started from.
    trigger_node_id: str = ""
    #: Per node, what arrived and what left by each port (RADD-921). The counts
    #: answer "did my filter narrow anything"; the samples answer "did it keep
    #: the right ones", which is the question someone debugging actually has.
    nodes: list[NodeResult] = Field(default_factory=list)
    #: Budget truncation, surfaced rather than buried in a log — a run that did
    #: less and a run that had less to do look identical without it.
    dropped: list[str] = Field(default_factory=list)
    #: What a VALIDATION graph would tell the submitter (spec 119). A dry run of
    #: a validate-triggered graph otherwise reports port counts and an empty
    #: `would_apply` — technically accurate and useless, since the only thing
    #: such a graph produces is these.
    findings: list["TestFinding"] = Field(default_factory=list)


class TestFinding(BaseModel):
    node_id: str
    message: str
    field: str = ""


class RunnableRuleRead(BaseModel):
    """Slim listing of MANUAL rules for the editor's `/` quick-action menu — visible
    to members (name only; conditions/actions stay admin-only)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class RuleRunRequest(BaseModel):
    item_id: uuid.UUID


class RuleRunResult(BaseModel):
    rule_id: uuid.UUID
    item_id: uuid.UUID
    ran: bool  # False = the item didn't match the rule's SLQ condition
