"""Shared compile-time helpers: the compilation context, operator checks,
value coercion (sentinels, enums, numbers, dates, item keys), polarity.
"""

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field as dc_field
from datetime import date, timedelta
from typing import Any

from sqlalchemy import ColumnElement, not_

from radd.modules.fields.models import FieldDefinition

from ..filters import NONE_LITERAL
from .catalog import ME_LITERAL, FieldOps, SlqField
from .errors import SlqError
from .lexer import CompareOp
from .parser import Comparison, Condition, EmptyCheck, Membership, Value

ITEM_KEY_RE = re.compile(r"^([A-Za-z][A-Za-z0-9]*)-([0-9]+)$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Relative date literals (spec 69): `today`, `today+3d`, `today-2w` (units d/w),
# resolved at COMPILE time against the server date. Bare words only — a quoted
# 'today' stays a literal (and fails the date check), like the me/none sentinels.
TODAY_LITERAL = "today"
RELATIVE_DATE_RE = re.compile(r"^today(?:(?P<sign>[+-])(?P<count>\d+)(?P<unit>[dw]))?$")
RELATIVE_UNIT_DAYS = {"d": 1, "w": 7}
LIKE_ESCAPE = "\\"


@dataclass(frozen=True)
class Context:
    """Everything a pure compile step needs (labels and bare epic/parent item
    keys pre-resolved by compile_query)."""

    definitions_by_key: Mapping[str, FieldDefinition]
    current_user_id: uuid.UUID
    label_ids_by_name: Mapping[str, tuple[uuid.UUID, ...]]
    # spec 83: uppercased key text -> item id via the spec-68 alias-aware
    # resolver; a missing entry means "no such item" -> positioned SlqError.
    ancestor_ids_by_key: Mapping[str, uuid.UUID] = dc_field(default_factory=dict)

    @property
    def field_names(self) -> list[str]:
        from radd.kernel import registries

        # builtins + plugin-registered SLQ fields (spec 94) + custom fields.
        return (
            [f.value for f in SlqField]
            + list(registries.slq_fields)
            + list(self.definitions_by_key)
        )


def check_ops(node: Condition, ops: FieldOps) -> None:
    """Reject operators the field's op surface doesn't carry (position-aware)."""
    match node:
        case Comparison() if node.op not in ops.compare:
            raise SlqError(
                f"operator '{node.op.value}' is not valid for field '{node.field}'",
                node.op_position,
            )
        case Membership() if not ops.membership:
            raise SlqError(f"IN is not valid for field '{node.field}'", node.field_position)
        case EmptyCheck() if not ops.empty:
            raise SlqError(f"IS EMPTY is not valid for field '{node.field}'", node.field_position)


def values_of(node: Comparison | Membership) -> tuple[Value, ...]:
    return (node.value,) if isinstance(node, Comparison) else node.values


def negated(node: Condition) -> bool:
    match node:
        case Comparison():
            return node.op is CompareOp.NE
        case Membership() | EmptyCheck():
            return node.negated
    return False


def polarity(node: Condition, clause: ColumnElement[bool]) -> ColumnElement[bool]:
    return not_(clause) if negated(node) else clause


def is_sentinel(value: Value, sentinel: str) -> bool:
    return not value.quoted and value.text == sentinel


def plain(value: Value, field: str) -> str:
    """A literal value: bare `me`/`none` are rejected where they have no meaning."""
    for sentinel in (ME_LITERAL, NONE_LITERAL):
        if is_sentinel(value, sentinel):
            raise SlqError(
                f"'{sentinel}' is not a valid value for field '{field}'", value.position
            )
    return value.text


def enum_values[E](node: Comparison | Membership, enum_cls: type[E]) -> list[E]:
    values = []
    for value in values_of(node):
        try:
            values.append(enum_cls(plain(value, node.field)))
        except ValueError:
            expected = ", ".join(member.value for member in enum_cls)  # type: ignore[attr-defined]
            raise SlqError(
                f"invalid {node.field} '{value.text}' — expected one of: {expected}",
                value.position,
            ) from None
    return values


def int_value(value: Value, field: str) -> int:
    try:
        return int(value.text)
    except ValueError:
        raise SlqError(
            f"field '{field}' expects a whole number, got '{value.text}'", value.position
        ) from None


def number_value(value: Value, field: str) -> float:
    try:
        return float(value.text)
    except ValueError:
        raise SlqError(
            f"field '{field}' expects a number, got '{value.text}'", value.position
        ) from None


def relative_date(value: Value, today: date) -> date | None:
    """`today`/`today+3d`/`today-2w` -> a concrete date; None when the value
    isn't a (bare) relative-date literal. Pure — `today` is injected."""
    if value.quoted:
        return None
    matched = RELATIVE_DATE_RE.match(value.text)
    if not matched:
        return None
    if matched.group("count") is None:
        return today
    days = int(matched.group("count")) * RELATIVE_UNIT_DAYS[matched.group("unit")]
    delta = timedelta(days=days)
    return today + delta if matched.group("sign") == "+" else today - delta


def date_value(value: Value, field: str) -> date:
    resolved = relative_date(value, date.today())
    if resolved is not None:
        return resolved
    if DATE_RE.match(value.text):
        try:
            return date.fromisoformat(value.text)
        except ValueError:
            pass
    raise SlqError(
        f"field '{field}' expects a date (YYYY-MM-DD) or a relative date "
        f"(today, today+3d, today-2w), got '{value.text}'",
        value.position,
    )


def item_key(value: Value, field: str) -> tuple[str, int]:
    """'TD-12' -> ('TD', 12)."""
    matched = ITEM_KEY_RE.match(plain(value, field))
    if not matched:
        raise SlqError(f"expected an item key like TD-12, got '{value.text}'", value.position)
    return matched.group(1).upper(), int(matched.group(2))


def compare(column: ColumnElement[Any], op: CompareOp, value: Any) -> ColumnElement[bool]:
    match op:
        case CompareOp.EQ:
            return column == value
        case CompareOp.NE:
            return column != value
        case CompareOp.GT:
            return column > value
        case CompareOp.GE:
            return column >= value
        case CompareOp.LT:
            return column < value
        case CompareOp.LE:
            return column <= value
    raise TypeError(op)  # pragma: no cover


def escape_like(text: str) -> str:
    return text.replace(LIKE_ESCAPE, LIKE_ESCAPE * 2).replace("%", r"\%").replace("_", r"\_")
