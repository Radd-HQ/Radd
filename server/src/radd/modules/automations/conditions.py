"""The event-side vocabulary every gate reads (spec 58, cut down by RADD-1265).

`EventFacts` is the plain-data view of one event the engine hands to every
gate; `_payload_path` addresses into its payload (lists fan out); `compare`
gives the operators their meaning. The nestable all/any/none CONDITION TREE
that used to live here is gone: the graph composes booleans (chain = AND,
fan-out = OR, the `false` port = NOT) and the named gates in `gates.py` each
ask one plain question, so a second boolean vocabulary taught nothing.

Pure module: no session, no I/O — unit-tested in tests/test_automation_gates.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .types import ConditionOperator

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
