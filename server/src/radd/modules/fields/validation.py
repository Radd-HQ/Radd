"""Registry-driven validation of custom_fields payloads. Core invariant — many modules rely on it."""

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from typing import Any

from radd.exceptions import RaddError

from .models import FieldDefinition
from .types import FieldType


class FieldValidationError(RaddError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


_CHECKS: dict[FieldType, tuple[Callable[[Any], bool], str]] = {
    FieldType.TEXT: (lambda v: isinstance(v, str), "must be a string"),
    FieldType.USER: (lambda v: isinstance(v, str), "must be a user identifier string"),
    FieldType.URL: (
        lambda v: isinstance(v, str) and v.startswith(("http://", "https://")),
        "must be an http(s) URL",
    ),
    FieldType.NUMBER: (_is_number, "must be a number"),
    FieldType.BOOLEAN: (lambda v: isinstance(v, bool), "must be a boolean"),
    FieldType.DATE: (_check_date, "must be an ISO date (YYYY-MM-DD)"),
    FieldType.DURATION: (
        lambda v: isinstance(v, int) and not isinstance(v, bool) and v >= 0,
        "must be whole minutes (integer >= 0)",
    ),
}


def check_field_value(
    field_type: FieldType, options: Sequence[str] | None, value: Any
) -> str | None:
    """Return an error message if `value` is invalid for the field type, else None.
    Definition-independent so schemas/service can validate a proposed default_value."""
    opts = options or []
    if field_type is FieldType.SELECT:
        if not isinstance(value, str) or value not in opts:
            return f"must be one of {list(opts)}"
        return None
    if field_type is FieldType.MULTI_SELECT:
        if (
            not isinstance(value, list)
            or not all(isinstance(v, str) for v in value)
            or not set(value) <= set(opts)
        ):
            return f"must be a list drawn from {list(opts)}"
        return None
    check, message = _CHECKS[field_type]
    return None if check(value) else message


def _check_value(definition: FieldDefinition, value: Any) -> str | None:
    return check_field_value(FieldType(definition.type), definition.options, value)


def apply_defaults(
    definitions: Sequence[FieldDefinition], values: Mapping[str, Any]
) -> dict[str, Any]:
    """Seed each definition's default_value for keys the caller omitted, returning a new
    dict. Only *absent* keys are filled — an explicit None is the caller's intent to leave
    the field empty, so it is preserved. Call on item create, before validation."""
    merged = dict(values)
    for definition in definitions:
        if definition.default_value is not None and definition.key not in merged:
            merged[definition.key] = definition.default_value
    return merged


def validate_custom_fields(
    definitions: Sequence[FieldDefinition], values: Mapping[str, Any]
) -> dict[str, Any]:
    """Validate against the registry. Returns the normalized dict to store.

    `None` clears an optional field (dropped from the result); required fields must be present
    and non-None.
    """
    by_key = {d.key: d for d in definitions}
    errors: list[str] = []
    normalized: dict[str, Any] = {}

    for key in values:
        if key not in by_key:
            errors.append(f"{key}: unknown field")

    for key, definition in by_key.items():
        value = values.get(key)
        if value is None:
            if definition.required:
                errors.append(f"{key}: required")
            continue
        problem = _check_value(definition, value)
        if problem:
            errors.append(f"{key}: {problem}")
        else:
            normalized[key] = value

    if errors:
        raise FieldValidationError(sorted(errors))
    return normalized
