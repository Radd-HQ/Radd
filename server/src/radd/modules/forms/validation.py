"""Form-submission validation — the form's own `required` overrides (spec 17).

The registry runs `validate_custom_fields` for type/unknown-key/registry-required checks
(422 via the fields module). On top of that a form field may be `required` even when the
underlying registry field is not; that override is checked here. Kept pure so the invariant
is unit-tested without a DB (mirrors test_field_grants / test_authz).
"""

from collections.abc import Mapping, Sequence
from typing import Any

from radd.exceptions import RaddError


class FormValidationError(RaddError):
    """A form submission violated the form's own required overrides (-> 422)."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def is_missing(value: Any) -> bool:
    """A required form field is unsatisfied when its submitted value is absent or blank.

    `None`, an empty string, and an empty list count as missing; falsey-but-present
    values (0, False) satisfy the requirement.
    """
    return value is None or value == "" or value == []


def missing_required_keys(
    fields: Sequence[Mapping[str, Any]], values: Mapping[str, Any]
) -> list[str]:
    """The field keys a form marks required but the submission omits (sorted)."""
    return sorted(
        field["field_key"]
        for field in fields
        if field.get("required") and is_missing(values.get(field["field_key"]))
    )
