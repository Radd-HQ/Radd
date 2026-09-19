"""Concrete condition nodes (spec 116 revision).

`gate.event` was one node holding a nestable all/any/none tree of
subject/operator/value. It could express anything and taught nothing: opening it
told you there were "event conditions" and nothing about what they were. It is
deleted (RADD-1265; a data migration converted stored trees).

These replace it with NAMED single tests — "field changed", "changed by",
"state category is" — each with a real form. The expressiveness is not lost,
because the GRAPH already composes booleans:

    AND  -> chain two gates
    OR   -> fan out from the trigger and merge into the same action
    NOT  -> take the `false` port

which is more legible than a nested tree and needs no second vocabulary.

Pure module: every evaluator takes `EventFacts` and a params dict and returns a
bool. No session, no I/O — unit-testable exactly like `conditions.py`.
"""

from __future__ import annotations

from typing import Any, Mapping

from .conditions import EventFacts, _payload_path, compare
from .types import (
    TYPE_GATE_PAYLOAD,
    ConditionOperator,
    TYPE_GATE_CHANGED_BY,
    TYPE_GATE_COMMENT,
    TYPE_GATE_FIELD_CHANGED,
    TYPE_GATE_PAGE_SPACE,
    TYPE_GATE_STATE_CATEGORY,
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


def state_category_is(facts: EventFacts, params: Mapping[str, Any]) -> bool:
    """Is the item's state category now one of these?

    The category AFTER the event, which is what "did this item just become done"
    needs — the payload carries it for item events.
    """
    wanted = {str(v).lower() for v in (params.get("categories") or [])}
    if not wanted:
        return False
    # `item.state.category` — RADD-922. This read `payload["state_category"]`,
    # a key NOTHING has ever emitted, so the node could only ever answer false:
    # configured, saved, and silently inert. `conditions.py` had the right path
    # (`state.category`) the whole time, which is how it went unnoticed.
    actual = ((facts.payload.get("item") or {}).get("state") or {}).get("category")
    return str(actual).lower() in wanted if actual is not None else False


THREAD_ANY, THREAD_ROOT, THREAD_REPLY = "any", "root", "reply"
VISIBILITY_ANY = "any"


def comment_is(facts: EventFacts, params: Mapping[str, Any]) -> bool:
    """Is the comment a root or a reply, and public or internal? (RADD-1248)

    Reads the comment event's own data: `parent_comment_id` (null on a root)
    and `visibility`. On an event that is not about a comment it answers False —
    a gate that can only be asked of a comment.
    """
    payload = facts.payload
    if "visibility" not in payload and "parent_comment_id" not in payload:
        return False
    thread = str(params.get("thread") or THREAD_ANY)
    is_reply = bool(payload.get("parent_comment_id"))
    if thread == THREAD_REPLY and not is_reply:
        return False
    if thread == THREAD_ROOT and is_reply:
        return False
    visibility = str(params.get("visibility") or VISIBILITY_ANY)
    if visibility != VISIBILITY_ANY and str(payload.get("visibility")) != visibility:
        return False
    return True


def page_space_is(facts: EventFacts, params: Mapping[str, Any]) -> bool:
    """Is the page this event is about in one of these spaces? (RADD-1248)

    A page event carries a top-level `page_space` ref; a page comment carries
    the space inside its `page` ref. Either is the answer; an event about no
    page answers False. Slugs, because that is what people read in the bar.
    """
    wanted = {str(v).strip().lower() for v in (params.get("spaces") or []) if str(v).strip()}
    if not wanted:
        return False
    payload = facts.payload
    space = payload.get("page_space")
    if not isinstance(space, dict):
        page = payload.get("page")
        space = page.get("space") if isinstance(page, dict) else None
    slug = space.get("slug") if isinstance(space, dict) else None
    hit = bool(slug) and str(slug).lower() in wanted
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


#: node type -> evaluator. The executor dispatches through this rather than an
#: `if node.type == …` ladder, so a new gate is one entry plus its spec.
GATE_EVALUATORS = {
    TYPE_GATE_PAYLOAD: payload_value_is,
    TYPE_GATE_FIELD_CHANGED: field_changed,
    TYPE_GATE_CHANGED_BY: changed_by,
    TYPE_GATE_STATE_CATEGORY: state_category_is,
    TYPE_GATE_COMMENT: comment_is,
    TYPE_GATE_PAGE_SPACE: page_space_is,
}
