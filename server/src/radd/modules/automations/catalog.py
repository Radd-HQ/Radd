"""Automation builder metadata (spec 58) + the trigger accessor.

Triggers are NO LONGER a hardcoded list. `TRIGGERS` is derived live from the
kernel **event-type registry** (docs/plugin-platform.md §3, chokepoint 1): every
plugin declares its triggerable events in its manifest (`event_types=…`), so a new
plugin's events appear here with **zero edits to this module** — the inversion of
the old `_SPECS` list that imported 21 modules' event enums.

Subjects, operators, and schedule kinds stay here: they are the condition-builder
*grammar* (how a rule expresses a condition), not per-event data, so they are not
plugin-contributed.

`item_scoped` triggers resolve a target item (the event's entity, or the payload's
`item_id`) — the SLQ condition and item actions apply to it. Rules on non-item
triggers still evaluate event conditions, but item actions skip.
"""

from dataclasses import dataclass

from radd.kernel import registries
from radd.kernel.specs import EventTypeSpec

from .types import ConditionOperator, ConditionSubject, ScheduleKind


def triggers() -> dict[str, EventTypeSpec]:
    """The automation trigger catalog — every registered event type marked as a
    trigger, read live from the kernel registry (chokepoint-1 inversion). Each
    spec carries `event_type`/`label`/`group`/`item_scoped`/`has_changes`, the
    shape the old `TriggerSpec` had, so consumers are unchanged."""
    return registries.triggers()


def __getattr__(name: str):
    """PEP 562: keep the `catalog.TRIGGERS` name working for existing consumers
    (router, engine, rule-write validation) — resolves to the live registry dict
    on each access, so it always reflects the currently-loaded plugins."""
    if name == "TRIGGERS":
        return registries.triggers()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# --- builder metadata (served by GET /automations/catalog for the UI) ---


@dataclass(frozen=True)
class SubjectSpec:
    key: str
    label: str
    needs_qualifier: bool = False
    qualifier_hint: str = ""
    requires_changes: bool = False  # only meaningful when the trigger has a diff


SUBJECTS: list[SubjectSpec] = [
    SubjectSpec(ConditionSubject.ACTOR, "Actor (who did it)"),
    SubjectSpec(
        ConditionSubject.CHANGED_FIELD, "Changed field", requires_changes=True
    ),
    SubjectSpec(
        ConditionSubject.OLD_VALUE,
        "Old value of field…",
        needs_qualifier=True,
        qualifier_hint="field, e.g. state / assignee / cf key",
        requires_changes=True,
    ),
    SubjectSpec(
        ConditionSubject.NEW_VALUE,
        "New value of field…",
        needs_qualifier=True,
        qualifier_hint="field, e.g. state / assignee / cf key",
        requires_changes=True,
    ),
    SubjectSpec(ConditionSubject.STATE_CATEGORY, "Item state category"),
    SubjectSpec(
        ConditionSubject.PAYLOAD,
        "Event payload path…",
        needs_qualifier=True,
        qualifier_hint="dotted path, e.g. visibility / labels / state.name",
    ),
]


@dataclass(frozen=True)
class OperatorSpec:
    key: str
    label: str
    needs_value: bool = True
    list_value: bool = False


# Spec 69: the schedule kinds the builder's "On a schedule" editor offers.
# (The schedule trigger itself is a sentinel like MANUAL — deliberately NOT in
# TRIGGERS, so the event engine can never fire it.)
SCHEDULE_KINDS: list[tuple[ScheduleKind, str]] = [
    (ScheduleKind.INTERVAL, "Every N minutes"),
    (ScheduleKind.DAILY, "Daily at a time"),
    (ScheduleKind.WEEKLY, "Weekly on chosen days"),
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
