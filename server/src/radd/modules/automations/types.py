import uuid
from enum import StrEnum

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


# Legacy alias — the sentinel predates the enum (kept so callers read naturally).
MANUAL_TRIGGER = AutomationTrigger.MANUAL.value


#: The shape of a scheduled rule's `schedule` JSONB (spec 69). Promoted to the
#: shared core util by spec 99 (backups schedule the same way); re-exported here
#: so this module's own vocabulary still reads from one place.
ScheduleKind = ScheduleKind


# Floor for interval schedules (spec 69) — protects the engine from 1-minute loops.
SCHEDULE_MIN_INTERVAL_MINUTES = 5


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


# ActionTypes that need the event's target item — everything not in this set
# is universal. The engine skip-logs item actions on itemless events.
ITEM_ACTIONS = frozenset(
    {
        ActionType.SET_STATE,
        ActionType.SET_PRIORITY,
        ActionType.SET_ASSIGNEE,
        ActionType.SET_TEAM,
        ActionType.ADD_LABEL,
        ActionType.REMOVE_LABEL,
        ActionType.SET_CYCLE,
        ActionType.SET_RELEASE,
        ActionType.SET_CUSTOM_FIELD,
        ActionType.ADD_COMMENT,
    }
)


# The complement — actions that run with or without a target item. Scheduled
# runs (spec 69) execute ITEM_ACTIONS per matching item and these exactly once.
UNIVERSAL_ACTIONS = frozenset(ActionType) - ITEM_ACTIONS


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
