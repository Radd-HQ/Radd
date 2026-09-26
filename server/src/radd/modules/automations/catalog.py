"""Automation builder metadata: the trigger catalog (read live from the kernel
event-type registry, so a plugin's events appear with no edit here), the
"Event value is" operators, and each node type's arity rule."""

from dataclasses import dataclass

from radd.kernel import registries
from radd.kernel.specs import EventTypeSpec

from .nodes import arity_rule
from .types import ArityRule, ConditionOperator, ScheduleKind


def triggers() -> dict[str, EventTypeSpec]:
    """Every registered event type marked `trigger=True`."""
    return registries.triggers()


def node_arities() -> dict[str, ArityRule]:
    """node type -> arity rule for EVERY node type, served so the editor's
    default cannot disagree with the engine's (RADD-918)."""
    return {key: arity_rule(key) for key in registries.automation_nodes}


# --- builder metadata (served by GET /automations/catalog for the UI) ---


@dataclass(frozen=True)
class OperatorSpec:
    key: str
    label: str
    needs_value: bool = True
    list_value: bool = False


# Spec 69: the schedule kinds the builder's "On a schedule" editor offers.
# (The schedule trigger itself is a sentinel like MANUAL — deliberately NOT in
# `triggers()`, so the event engine can never fire it.)
SCHEDULE_KINDS: list[tuple[ScheduleKind, str]] = [
    (ScheduleKind.INTERVAL, "Every N minutes"),
    (ScheduleKind.DAILY, "Daily at a time"),
    (ScheduleKind.WEEKLY, "Weekly on chosen days"),
    (ScheduleKind.MONTHLY, "Monthly on a chosen day"),
    (ScheduleKind.CRON, "Custom (cron expression)"),
]


OPERATORS: list[OperatorSpec] = [
    OperatorSpec(ConditionOperator.EQ, "is"),
    OperatorSpec(ConditionOperator.NEQ, "is not"),
    OperatorSpec(ConditionOperator.IN, "is any of", list_value=True),
    OperatorSpec(ConditionOperator.NOT_IN, "is none of", list_value=True),
    OperatorSpec(ConditionOperator.CONTAINS, "contains"),
    OperatorSpec(ConditionOperator.NOT_CONTAINS, "doesn't contain"),
    OperatorSpec(ConditionOperator.IS_SET, "is set", needs_value=False),
    OperatorSpec(ConditionOperator.NOT_SET, "is not set", needs_value=False),
    OperatorSpec(ConditionOperator.MATCHES, "matches regex"),
    OperatorSpec(ConditionOperator.GT, "is greater than"),
    OperatorSpec(ConditionOperator.LT, "is less than"),
]
