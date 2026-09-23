"""Pure transition-guard evaluation (specs 61/107) — no DB, unit-tested.

A transition row carries `rules` = [{check, params}]; `evaluate` turns them into
human-readable failure strings against an ItemSnapshot the service builds. Kept
pure so the invariant is tested without a DB (mirrors forms/validation.py).

Spec 107: every data check is ONE shape — require_field {kind, key, op, values}
over builtins + custom fields (the old five presence checks are migrated rows);
require_approval carries per-entry approver rules.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from radd.exceptions import RaddError

from radd.modules.fields.types import FieldType
from .types import (
    ApproverKind,
    BUILTIN_LABELS,
    DATE_BUILTINS,
    BuiltinField,
    ConditionKind,
    ConditionOp,
    TransitionCheck,
)


class TransitionError(RaddError):
    """A state change violated the project's transition rules (-> 422)."""

    def __init__(self, errors: list[str], from_state: str | None, to_state: str):
        self.errors = errors
        self.from_state = from_state
        self.to_state = to_state
        super().__init__("; ".join(errors))


@dataclass(frozen=True)
class ItemSnapshot:
    """What the guards may look at — resolved by the service (estimate via the
    timelogging seam, comment count via the comments seam, labels via the
    item_labels rows). `builtin` maps BuiltinField values to NORMALIZED values:
    ids/enums as strings, dates as ISO strings, labels as a string list,
    estimate as bool-or-None, comment as a count-or-None (so set/empty read
    uniformly: None/""/[] is empty)."""

    builtin: Mapping[str, Any] = field(default_factory=dict)
    custom_fields: Mapping[str, Any] = field(default_factory=dict)
    field_labels: Mapping[str, str] = field(default_factory=dict)  # cf key -> display name
    # Spec 71: string state ids the item holds a CONSUMABLE approved request for
    # (resolved via the approvals module's deferred seam; module absent = empty).
    approved_to_state_ids: frozenset[str] = frozenset()
    has_unresolved_threads: bool = False


def is_empty(value: Any) -> bool:
    """A required field is unsatisfied when absent or blank; falsey-but-present
    values (0, False) satisfy it (same contract as forms.validation.is_missing)."""
    return value is None or value == "" or value == []


# The legacy failure strings, kept verbatim — they're in toasts, tooltips and
# tests, and they read better than the generic phrasing for these four.
_SET_SPECIALS: dict[str, str] = {
    BuiltinField.ASSIGNEE.value: "an assignee is required",
    BuiltinField.TEAM.value: "a team is required",
    BuiltinField.ESTIMATE.value: "an estimate is required",
    BuiltinField.COMMENT.value: "at least one comment is required",
}


def _as_strings(value: Any) -> set[str]:
    """The item-side value as a comparison set (multi-valued -> its members)."""
    if is_empty(value):
        return set()
    if isinstance(value, bool):
        return {"true" if value else "false"}
    if isinstance(value, (list, tuple)):
        return {str(entry) for entry in value}
    return {str(value)}


def _as_number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _condition_met(op: ConditionOp, value: Any, values: Sequence[str], numeric: bool) -> bool:
    if op is ConditionOp.SET:
        return not is_empty(value)
    if op is ConditionOp.EMPTY:
        return is_empty(value)
    if op is ConditionOp.IS or op is ConditionOp.IS_NOT:
        if numeric:
            have = {_as_number(entry) for entry in _as_strings(value)} - {None}
            want = {_as_number(entry) for entry in values} - {None}
        else:
            have, want = _as_strings(value), set(values)
        overlap = bool(have & want)
        # IS needs a present, matching value; IS_NOT passes on empty (nothing
        # isn't the value) and fails only on an actual match.
        return overlap if op is ConditionOp.IS else not overlap
    # gte/lte: an absent value can't satisfy a bound.
    if is_empty(value) or not values:
        return False
    if numeric:
        have_num, bound = _as_number(value), _as_number(values[0])
        if have_num is None or bound is None:
            return False
        return have_num >= bound if op is ConditionOp.GTE else have_num <= bound
    # Dates ride ISO strings (YYYY-MM-DD), which order lexicographically.
    text = str(value)
    return text >= values[0] if op is ConditionOp.GTE else text <= values[0]


def _shown_values(params: Mapping[str, Any]) -> list[str]:
    display = [str(v) for v in params.get("display") or []]
    values = [str(v) for v in params.get("values") or []]
    return display if len(display) == len(values) and display else values


def _field_failure(label: str, key: str, op: ConditionOp, params: Mapping[str, Any], date_like: bool) -> str:
    shown = _shown_values(params)
    listed = ", ".join(shown)
    if op is ConditionOp.SET:
        return _SET_SPECIALS.get(key, f'"{label}" must be set')
    if op is ConditionOp.EMPTY:
        if key == BuiltinField.COMMENT.value:
            return "comments are not allowed"
        return f'"{label}" must be empty'
    if op is ConditionOp.IS:
        return f'"{label}" must be {listed}' if len(shown) == 1 else f'"{label}" must be one of {listed}'
    if op is ConditionOp.IS_NOT:
        return f'"{label}" must not be {listed}' if len(shown) == 1 else f'"{label}" must not be any of {listed}'
    if op is ConditionOp.GTE:
        return f'"{label}" must be on or after {listed}' if date_like else f'"{label}" must be at least {listed}'
    return f'"{label}" must be on or before {listed}' if date_like else f'"{label}" must be at most {listed}'


def _evaluate_field(params: Mapping[str, Any], snapshot: ItemSnapshot) -> str | None:
    """One require_field condition -> a failure string or None. Malformed params
    are skipped (write-validation rejects them; old data must never 500)."""
    key = str(params.get("key") or "")
    try:
        kind = ConditionKind(params.get("kind"))
        op = ConditionOp(params.get("op"))
    except ValueError:
        return None
    if not key:
        return None
    values = [str(v) for v in params.get("values") or []]
    if kind is ConditionKind.CUSTOM:
        value = snapshot.custom_fields.get(key)
        label = snapshot.field_labels.get(key, key)
        field_type = str(params.get("type") or "")
        numeric = field_type in (FieldType.NUMBER.value, FieldType.DURATION.value)
        date_like = field_type == FieldType.DATE.value
    else:
        value = snapshot.builtin.get(key)
        try:
            label = BUILTIN_LABELS[BuiltinField(key)]
            date_like = BuiltinField(key) in DATE_BUILTINS
        except ValueError:
            return None
        numeric = False
    if _condition_met(op, value, values, numeric):
        return None
    return _field_failure(label, key, op, params, date_like)


def _approval_failure(params: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for entry in params.get("approvers") or []:
        name = entry.get("name") or entry.get("id") or "?"
        if entry.get("kind") == ApproverKind.TEAM.value:
            parts.append(f"{int(entry.get('required') or 1)} of {name}")
        else:
            parts.append(str(name))
    return f"approval required ({'; '.join(parts)})" if parts else "approval required"


def evaluate(
    rules: Sequence[Mapping[str, Any]],
    snapshot: ItemSnapshot,
    to_state_id: str | None = None,
) -> list[str]:
    """Failure strings for every unsatisfied rule (empty = the transition passes).
    Unknown checks are skipped — rules are validated against TransitionCheck on write.
    `to_state_id` is the target state (spec 71): require_approval passes iff the
    snapshot holds an approved request for it; its failure sorts LAST so guard
    strings compose (fix the data first, then request approval)."""
    failures: list[str] = []
    approval_failures: list[str] = []
    for rule in rules:
        try:
            check = TransitionCheck(rule.get("check"))
        except ValueError:
            continue
        params = rule.get("params") or {}
        if check is TransitionCheck.REQUIRE_FIELD:
            failure = _evaluate_field(params, snapshot)
            if failure is not None:
                failures.append(failure)
        elif check is TransitionCheck.REQUIRE_APPROVAL:
            if to_state_id is None or to_state_id not in snapshot.approved_to_state_ids:
                approval_failures.append(_approval_failure(params))
        elif check is TransitionCheck.REQUIRE_RESOLVED_THREADS:
            if snapshot.has_unresolved_threads:
                failures.append("all threads must be resolved (including internal threads)")
        elif check is TransitionCheck.REQUIRE_RELEASE:
            if is_empty(snapshot.builtin.get(BuiltinField.RELEASE.value)):
                failures.append("a release is required")
    return failures + approval_failures


def checks_in(rules: Sequence[Mapping[str, Any]]) -> set[TransitionCheck]:
    """The distinct checks a rule list uses — lets the service skip snapshot
    lookups no rule asks about."""
    found: set[TransitionCheck] = set()
    for rule in rules:
        try:
            found.add(TransitionCheck(rule.get("check")))
        except ValueError:
            continue
    return found


def conditions_met(
    conditions: Sequence[Mapping[str, Any]], snapshot: ItemSnapshot
) -> bool:
    """Applies-when resolution (spec 107 follow-up): every bare condition dict
    passes against the snapshot (empty list = applies to every item; malformed
    entries skip, like evaluate)."""
    return all(_evaluate_field(condition, snapshot) is None for condition in conditions)


def _rule_conditions(rules: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [
        rule.get("params") or {}
        for rule in rules
        if rule.get("check") == TransitionCheck.REQUIRE_FIELD.value
    ]


def condition_builtin_keys(conditions: Sequence[Mapping[str, Any]]) -> set[str]:
    """BuiltinField keys referenced by bare condition dicts — the service
    resolves only the expensive ones (labels query, estimate/comment seams)
    on demand."""
    return {
        str(condition.get("key") or "")
        for condition in conditions
        if condition.get("kind") == ConditionKind.BUILTIN.value
    }


def has_custom_condition(conditions: Sequence[Mapping[str, Any]]) -> bool:
    return any(
        condition.get("kind") == ConditionKind.CUSTOM.value for condition in conditions
    )


def builtin_keys_in(rules: Sequence[Mapping[str, Any]]) -> set[str]:
    """BuiltinField keys referenced by require_field rows."""
    return condition_builtin_keys(_rule_conditions(rules))


def has_custom_conditions(rules: Sequence[Mapping[str, Any]]) -> bool:
    return has_custom_condition(_rule_conditions(rules))
