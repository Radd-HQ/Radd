"""Unit tests for intake-form submission validation (spec 17) — the registry core.

The novel invariant a form adds on top of the field registry is its *own* `required`
overrides: a form field may be required even when the underlying registry field is not.
That check is pure (`forms/validation.py`), so it is unit-tested here without a DB; the
end-to-end submit flow (defaults resolution + registry validation) is exercised by
`scripts/demo_forms.sh`.
"""

from radd.modules.forms.validation import (
    FormValidationError,
    is_missing,
    missing_required_keys,
)


def field(key: str, required: bool = False) -> dict:
    return {"field_key": key, "required": required}


# --- is_missing: blank counts as missing, falsey-but-present does not ---


def test_is_missing_treats_blank_as_missing():
    assert is_missing(None)
    assert is_missing("")
    assert is_missing([])


def test_is_missing_accepts_falsey_present_values():
    assert not is_missing(0)
    assert not is_missing(False)
    assert not is_missing("x")
    assert not is_missing(["a"])


# --- missing_required_keys ---


def test_flags_only_required_and_absent_fields():
    fields = [
        field("severity", required=True),
        field("area", required=True),
        field("note", required=False),
    ]
    # severity provided, area + note omitted; only the required-and-absent area is flagged.
    assert missing_required_keys(fields, {"severity": "high"}) == ["area"]


def test_optional_fields_are_never_flagged():
    fields = [field("note", required=False), field("link", required=False)]
    assert missing_required_keys(fields, {}) == []


def test_blank_submissions_count_as_missing_and_sort():
    fields = [
        field("b", required=True),
        field("a", required=True),
        field("c", required=True),
    ]
    assert missing_required_keys(fields, {"a": "", "b": [], "c": None}) == ["a", "b", "c"]


def test_falsey_present_values_satisfy_a_required_field():
    fields = [field("count", required=True), field("flag", required=True)]
    assert missing_required_keys(fields, {"count": 0, "flag": False}) == []


def test_no_form_fields_means_nothing_required():
    assert missing_required_keys([], {"anything": "goes"}) == []


# --- the 422 carrier ---


def test_form_validation_error_keeps_and_joins_the_offending_fields():
    err = FormValidationError(["area: required", "severity: required"])
    assert err.errors == ["area: required", "severity: required"]
    assert "area: required" in str(err)
    assert "severity: required" in str(err)
