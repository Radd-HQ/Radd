"""The built-in named gates (spec 116): each asks one plain question with a real
form; the graph composes them (chain = AND, fan-out = OR, the `false` port = NOT).
Pure — every evaluator takes `EventFacts` and params and returns a bool.
"""

from __future__ import annotations

from typing import Any, Mapping

from .conditions import EventFacts, _payload_path, compare
from .types import (
    ConditionOperator,
)

#: `from`/`to` accept either "any value" or an explicit set. Kept as an explicit
#: mode rather than "empty list means any", because an empty list is also what a
#: half-filled form produces — and silently treating that as "match everything"
#: is how an automation fires on changes nobody meant to catch.
MODE_ANY = "any"
MODE_SPECIFIC = "specific"
MODE_EMPTY = "empty"  # the field was cleared / was not set


def _side_matches(mode: str, values: list[str], actual: Any) -> bool:
    if mode == MODE_ANY:
        return True
    if mode == MODE_EMPTY:
        return actual in (None, "", [], {})
    # Compared as strings: an event payload carries whatever the field's type
    # serialises to, and the form collects text. Priority "high" and state
    # "In Review" both arrive as strings; a custom number field arrives as a
    # number, so str() on both sides keeps "3" == 3 working.
    return any(str(value) == str(actual) for value in values)


def field_changed(facts: EventFacts, params: Mapping[str, Any]) -> bool:
    """Did `field` change, from something matching `from`, to something matching `to`?

    Reads the event's own diff (`item.updated` carries
    `[{field, from, to}, …]`), so it is exact about WHICH transition happened —
    unlike an SLQ filter, which can only see the item's state now and would also
    match an item that was already in the target state.
    """
    field = str(params.get("field") or "")
    if not field:
        return False
    from_mode = str(params.get("from_mode") or MODE_ANY)
    to_mode = str(params.get("to_mode") or MODE_ANY)
    from_values = [str(v) for v in (params.get("from_values") or [])]
    to_values = [str(v) for v in (params.get("to_values") or [])]

    for change in facts.changes:
        if str(change.get("field")) != field:
            continue
        if _side_matches(from_mode, from_values, change.get("from")) and _side_matches(
            to_mode, to_values, change.get("to")
        ):
            return True
    return False


def changed_by(facts: EventFacts, params: Mapping[str, Any]) -> bool:
    """Was the event caused by one of these people?

    Matches on id, email or name — the same three the actor subject accepted —
    because a form may collect any of them depending on which picker filled it.
    """
    wanted = {str(v).lower() for v in (params.get("users") or []) if str(v).strip()}
    if not wanted:
        return False
    actual = {
        str(value).lower()
        for value in (facts.actor_id, facts.actor_email, facts.actor_name)
        if value
    }
    hit = bool(wanted & actual)
    return not hit if params.get("negate") else hit


#: Operators that take no value; the form hides the value box for them.
VALUELESS_OPERATORS = frozenset({ConditionOperator.IS_SET, ConditionOperator.NOT_SET})
#: Operators whose value is a LIST.
LIST_OPERATORS = frozenset({ConditionOperator.IN, ConditionOperator.NOT_IN})


def payload_value_is(facts: EventFacts, params: Mapping[str, Any]) -> bool:
    """Does the value at `path` in the event payload satisfy `operator value`?
    (RADD-1265 — "Event value is", the one open-ended gate.)

    The only gate that reads the payload by ADDRESS rather than by name, which
    is what makes it the escape hatch: `release.status` on a release event,
    `form_id` on a validation run, `changes.field` on an update. A list at the
    path fans out (`labels` → each label), so `contains` and `in` read naturally.
    An empty path answers False: a half-filled form must not match everything.
    """
    path = str(params.get("path") or "").strip()
    if not path:
        return False
    try:
        operator = ConditionOperator(str(params.get("operator") or ConditionOperator.EQ))
    except ValueError:
        return False
    value = params.get("value")
    if operator in LIST_OPERATORS and not isinstance(value, list):
        value = [v.strip() for v in str(value or "").split(",") if v.strip()]
    if operator not in VALUELESS_OPERATORS and value in (None, "", []):
        return False
    hit = compare(_payload_path(facts.payload, path), operator, value)
    return not hit if params.get("negate") else hit


def project_is(facts: EventFacts, params: Mapping[str, Any]) -> bool:
    """Is the event about a project in this set? (RADD-1267)

    Reads the `project` ref the kernel writes for any event whose subjects
    name one, and the item ref's own project for item-scoped events. Keys,
    because that is what people write everywhere else (`project = TD`). An
    event about no project answers False.
    """
    wanted = {str(v).strip().casefold() for v in (params.get("projects") or []) if str(v).strip()}
    if not wanted:
        return False
    payload = facts.payload
    ref = payload.get("project")
    if not isinstance(ref, dict):
        item = payload.get("item")
        ref = item.get("project") if isinstance(item, dict) else None
    key = ref.get("key") if isinstance(ref, dict) else None
    hit = bool(key) and str(key).casefold() in wanted
    return not hit if params.get("negate") else hit
