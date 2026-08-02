import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from radd.modules.comments.types import CommentVisibility
from radd.modules.items.enums import Priority

from radd import schedule as schedule_math

from . import catalog, conditions
from .types import (
    SCHEDULE_MIN_INTERVAL_MINUTES,
    ActionType,
    AutomationTrigger,
    ConditionOperator,
    ConditionSubject,
    GroupOp,
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


class SetPriorityParams(BaseModel):
    priority: Priority


class SetAssigneeParams(BaseModel):
    assignee: str = Field(min_length=1)  # user email, or the literal "none" to clear


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
    project: str = Field(min_length=1)  # project KEY
    title: str = Field(min_length=1, max_length=500)  # template
    description: str = Field(default="", max_length=10_000)  # template
    priority: Priority | None = None


class SendWebhookParams(BaseModel):
    url: str = Field(min_length=1, max_length=1000, pattern=r"^https?://")
    # Optional HMAC-SHA256 of the body, hex in X-Radd-Signature.
    secret: str = Field(default="", max_length=200)


class PostChatParams(BaseModel):
    # A Google Chat / Slack-style incoming webhook: POSTs {"text": message}.
    webhook_url: str = Field(min_length=1, max_length=1000, pattern=r"^https?://")
    message: str = Field(min_length=1, max_length=4000)  # template


class NotifyUserParams(BaseModel):
    user: str = Field(min_length=1)  # user email
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


# --- schedule config (spec 69) — the `schedule` JSONB of scheduled rules ---


class ScheduleConfig(BaseModel):
    """{kind, minutes|time, weekdays}: interval every N>=5 minutes, daily at
    HH:MM, or weekly at HH:MM on the listed weekdays (0=Mon, non-empty).
    Times run on the instance clock (`settings.scheduler_tz`)."""

    kind: ScheduleKind
    minutes: int | None = Field(default=None, ge=SCHEDULE_MIN_INTERVAL_MINUTES)
    time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    weekdays: list[int] | None = None

    @model_validator(mode="after")
    def _check_shape(self) -> "ScheduleConfig":
        if self.kind is ScheduleKind.INTERVAL:
            if self.minutes is None:
                raise ValueError("an interval schedule needs `minutes`")
            if self.time is not None or self.weekdays is not None:
                raise ValueError("an interval schedule takes only `minutes`")
            return self
        if self.time is None:
            raise ValueError(f"a {self.kind.value} schedule needs `time` (HH:MM)")
        try:
            schedule_math.parse_hh_mm(self.time)
        except ValueError:
            raise ValueError(f"invalid time {self.time!r} — expected HH:MM") from None
        if self.minutes is not None:
            raise ValueError(f"a {self.kind.value} schedule does not take `minutes`")
        if self.kind is ScheduleKind.DAILY:
            if self.weekdays is not None:
                raise ValueError("a daily schedule does not take `weekdays`")
            return self
        if not self.weekdays:
            raise ValueError("a weekly schedule needs at least one weekday (0=Mon)")
        if any(day < 0 or day > 6 for day in self.weekdays):
            raise ValueError("weekdays must be 0 (Mon) through 6 (Sun)")
        if len(set(self.weekdays)) != len(self.weekdays):
            raise ValueError("weekdays must not repeat")
        return self


# --- rule CRUD schemas ---


def _known_trigger(value: str) -> str:
    if value not in set(AutomationTrigger) and value not in catalog.TRIGGERS:
        raise ValueError(f"unknown trigger {value!r} — see GET /automations/catalog")
    return value


class RuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    enabled: bool = True
    # An event type from the catalog ("item.updated", "comment.created", …) or a
    # sentinel: "manual" (on-demand) / "schedule" (spec 69, needs `schedule`).
    trigger: str = Field(max_length=100)
    # Structured conditions on the EVENT itself (who/what changed); None = always.
    event_conditions: ConditionGroup | None = None
    condition_slq: str = Field(default="", max_length=4000)
    actions: list[Action] = Field(min_length=1)
    position: int = 0
    # Spec 69: present iff trigger == "schedule" (cross-checked in the service).
    schedule: ScheduleConfig | None = None

    @field_validator("trigger")
    @classmethod
    def _trigger_known(cls, value: str) -> str:
        return _known_trigger(value)


class RuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    enabled: bool | None = None
    trigger: str | None = Field(default=None, max_length=100)
    # Explicit null clears the conditions (model_fields_set distinguishes).
    event_conditions: ConditionGroup | None = None
    condition_slq: str | None = Field(default=None, max_length=4000)
    actions: list[Action] | None = Field(default=None, min_length=1)
    position: int | None = None
    # Explicit null clears the schedule (model_fields_set distinguishes).
    schedule: ScheduleConfig | None = None

    @field_validator("trigger")
    @classmethod
    def _trigger_known(cls, value: str | None) -> str | None:
        return value if value is None else _known_trigger(value)


class RuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    enabled: bool
    trigger: str
    event_conditions: dict[str, Any] | None
    condition_slq: str
    actions: list[dict[str, Any]]
    position: int
    # Spec 69: the stored schedule config + the scheduler's bookkeeping (the
    # next/last-run stamps live in automation_schedule_state — the service
    # hydrates them via `rule_reads`; None for event/manual rules).
    schedule: dict[str, Any] | None = None
    next_run_at: UtcDatetime | None = None
    last_run_at: UtcDatetime | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime


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


class CatalogRead(BaseModel):
    triggers: list[TriggerInfo]
    subjects: list[SubjectInfo]
    operators: list[OperatorInfo]
    manual_trigger: str = AutomationTrigger.MANUAL.value
    # Spec 69: the "On a schedule" sentinel + the schedule kinds the builder offers.
    schedule_trigger: str = AutomationTrigger.SCHEDULE.value
    schedule_kinds: list[ScheduleKindInfo] = []


# --- /test dry-run preview ---


class RuleTestRequest(BaseModel):
    item_id: uuid.UUID


class ActionPreview(BaseModel):
    type: ActionType
    params: dict[str, Any]
    resolves: bool  # would the action's target(s) resolve at apply time?
    detail: str


class RuleTestResult(BaseModel):
    rule_id: uuid.UUID
    item_id: uuid.UUID
    matched: bool
    would_apply: list[ActionPreview]


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
