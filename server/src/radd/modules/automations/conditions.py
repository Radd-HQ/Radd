"""Structured event conditions (spec 58): a nestable all/any/none tree evaluated
against the triggering EVENT — who acted, which fields changed, old/new values,
arbitrary payload paths. Complements the SLQ condition (which matches the item's
CURRENT state); together: "state changed to something in the done category, by
this user, on an item matching this query".

Pure module: `event_facts` extracts a plain-data view of an event, `matches`
evaluates a stored condition tree against it. No session, no I/O — unit-tested
in tests/test_automation_conditions.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .types import ConditionOperator, ConditionSubject, GroupOp

# Guard rails for hostile/degenerate stored trees (validated on write, enforced
# again on eval so a hand-crafted DB row can't wedge the engine).
MAX_DEPTH = 5
MAX_NODES = 50
_REGEX_MAX = 200


@dataclass(frozen=True)
class EventFacts:
    """Plain-data view of one event, prepared by the engine for evaluation."""

    event_type: str
    actor_id: str | None  # str(uuid), or None for anonymous/system-less events
    actor_email: str | None
    actor_name: str | None
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def changes(self) -> list[dict[str, Any]]:
        """item.updated field diff: [{"field", "from", "to"}, ...]; [] elsewhere."""
        raw = self.payload.get("changes")
        return raw if isinstance(raw, list) else []


# --- subject resolution: each subject yields the values it stands for ---


def _payload_path(payload: Any, path: str) -> list[Any]:
    """Resolve a dotted path; lists fan out. Missing keys resolve to nothing."""
    values: list[Any] = [payload]
    for part in path.split("."):
        next_values: list[Any] = []
        for value in values:
            if isinstance(value, list):
                value_items = value
            else:
                value_items = [value]
            for element in value_items:
                if isinstance(element, dict) and part in element:
                    next_values.append(element[part])
        values = next_values
        if not values:
            break
    # A terminal list value fans out to its elements (labels, watchers, …).
    flat: list[Any] = []
    for value in values:
        flat.extend(value if isinstance(value, list) else [value])
    return [value for value in flat if value is not None]


def _change_name(entry: dict[str, Any]) -> str:
    """A diff entry's user-facing field name — custom-field entries carry the
    real key under "key" (their "field" is the literal "custom_field")."""
    if entry.get("field") == "custom_field":
        return str(entry.get("key") or entry.get("name") or "custom_field")
    return str(entry.get("field", ""))


def _change_entry(facts: EventFacts, field_name: str) -> dict[str, Any] | None:
    wanted = field_name.strip().casefold()
    for entry in facts.changes:
        if _change_name(entry).casefold() == wanted:
            return entry
    return None


def resolve_subject(
    facts: EventFacts, subject: ConditionSubject, qualifier: str | None
) -> list[Any]:
    """The value(s) a subject stands for in this event; [] = nothing resolved."""
    match subject:
        case ConditionSubject.ACTOR:
            return [v for v in (facts.actor_id, facts.actor_email, facts.actor_name) if v]
        case ConditionSubject.CHANGED_FIELD:
            return [name for entry in facts.changes if (name := _change_name(entry))]
        case ConditionSubject.OLD_VALUE:
            # Set-valued fields (labels, links) diff as added/removed, not from/to:
            # "old value" naturally reads as what was removed.
            entry = _change_entry(facts, qualifier or "")
            if entry is None:
                return []
            return _payload_path(entry, "from") or _payload_path(entry, "removed")
        case ConditionSubject.NEW_VALUE:
            entry = _change_entry(facts, qualifier or "")
            if entry is None:
                return []
            return _payload_path(entry, "to") or _payload_path(entry, "added")
        case ConditionSubject.STATE_CATEGORY:
            return _payload_path(facts.payload, "item.state.category")
        case ConditionSubject.PAYLOAD:
            return _payload_path(facts.payload, (qualifier or "").strip())
    return []  # pragma: no cover — exhaustive over the enum


# --- comparison ---


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _norm(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value).strip().casefold()


def _scalar_eq(resolved: Any, expected: Any) -> bool:
    left_num, right_num = _as_number(resolved), _as_number(expected)
    if left_num is not None and right_num is not None:
        return left_num == right_num
    return _norm(resolved) == _norm(expected)


def _expected_list(expected: Any) -> list[Any]:
    return expected if isinstance(expected, list) else [expected]


def compare(resolved: list[Any], operator: ConditionOperator, expected: Any) -> bool:
    """Operator semantics over the resolved value set (empty set = unresolved)."""
    match operator:
        case ConditionOperator.IS_SET:
            return len(resolved) > 0
        case ConditionOperator.NOT_SET:
            return len(resolved) == 0
        case ConditionOperator.EQ:
            return any(
                _scalar_eq(value, want) for value in resolved for want in _expected_list(expected)
            )
        case ConditionOperator.NEQ:
            return not any(
                _scalar_eq(value, want) for value in resolved for want in _expected_list(expected)
            )
        case ConditionOperator.IN:
            return any(
                _scalar_eq(value, want) for value in resolved for want in _expected_list(expected)
            )
        case ConditionOperator.NOT_IN:
            return not any(
                _scalar_eq(value, want) for value in resolved for want in _expected_list(expected)
            )
        case ConditionOperator.CONTAINS:
            # Membership over a multi-valued subject; substring over a single string.
            if len(resolved) == 1 and isinstance(resolved[0], str):
                return _norm(expected) in _norm(resolved[0])
            return any(_scalar_eq(value, expected) for value in resolved)
        case ConditionOperator.NOT_CONTAINS:
            return not compare(resolved, ConditionOperator.CONTAINS, expected)
        case ConditionOperator.MATCHES:
            pattern = str(expected)[:_REGEX_MAX]
            try:
                compiled = re.compile(pattern, re.IGNORECASE)
            except re.error:
                return False
            return any(compiled.search(str(value)) for value in resolved)
        case ConditionOperator.GT | ConditionOperator.LT:
            want = _as_number(expected)
            if want is None:
                return False
            numbers = [n for n in (_as_number(value) for value in resolved) if n is not None]
            if operator is ConditionOperator.GT:
                return any(n > want for n in numbers)
            return any(n < want for n in numbers)
    return False  # pragma: no cover — exhaustive over the enum


# --- tree evaluation ---


def _count_nodes(node: dict[str, Any]) -> int:
    children = node.get("conditions")
    if not isinstance(children, list):
        return 1
    return 1 + sum(_count_nodes(child) for child in children if isinstance(child, dict))


def tree_depth(node: dict[str, Any]) -> int:
    children = node.get("conditions")
    if not isinstance(children, list):
        return 1
    return 1 + max(
        (tree_depth(child) for child in children if isinstance(child, dict)), default=0
    )


def _eval_node(facts: EventFacts, node: dict[str, Any], depth: int) -> bool:
    if depth > MAX_DEPTH:
        return False
    children = node.get("conditions")
    if isinstance(children, list):  # group node
        results = (
            _eval_node(facts, child, depth + 1) for child in children if isinstance(child, dict)
        )
        match GroupOp(node.get("op", GroupOp.ALL.value)):
            case GroupOp.ALL:
                return all(results)
            case GroupOp.ANY:
                return any(results)
            case GroupOp.NONE:
                return not any(results)
        return False  # pragma: no cover
    resolved = resolve_subject(
        facts, ConditionSubject(node["subject"]), node.get("qualifier")
    )
    return compare(resolved, ConditionOperator(node["operator"]), node.get("value"))


def matches(facts: EventFacts, tree: dict[str, Any] | None) -> bool:
    """Does the event satisfy the stored condition tree? None/empty = always.
    Malformed nodes raise (the engine catches per rule and logs)."""
    if not tree or not tree.get("conditions"):
        return True
    if _count_nodes(tree) > MAX_NODES:
        return False
    return _eval_node(facts, tree, 1)
