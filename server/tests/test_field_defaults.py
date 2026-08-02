"""Field default values (spec 50 follow-up) — the pure registry core.

`check_field_value` validates a proposed default against a type/options pair;
`apply_defaults` seeds definition defaults onto an item-create payload, filling
only the keys the caller omitted. Both are pure, so they test with stubs.
"""

from radd.modules.fields.types import FieldType
from radd.modules.fields.validation import apply_defaults, check_field_value


class StubDef:
    """Duck-types the two attrs apply_defaults reads off a FieldDefinition."""

    def __init__(self, key: str, default_value=None):
        self.key = key
        self.default_value = default_value


def test_check_field_value_accepts_valid_by_type():
    assert check_field_value(FieldType.TEXT, None, "hi") is None
    assert check_field_value(FieldType.NUMBER, None, 3.5) is None
    assert check_field_value(FieldType.BOOLEAN, None, True) is None
    assert check_field_value(FieldType.DATE, None, "2026-07-20") is None
    assert check_field_value(FieldType.DURATION, None, 90) is None
    assert check_field_value(FieldType.SELECT, ["a", "b"], "a") is None
    assert check_field_value(FieldType.MULTI_SELECT, ["a", "b"], ["a"]) is None


def test_check_field_value_rejects_mismatch():
    assert check_field_value(FieldType.NUMBER, None, "nope") is not None
    assert check_field_value(FieldType.BOOLEAN, None, 1) is not None  # bool is not int here
    assert check_field_value(FieldType.DATE, None, "not-a-date") is not None
    assert check_field_value(FieldType.DURATION, None, -1) is not None
    assert check_field_value(FieldType.SELECT, ["a", "b"], "z") is not None
    assert check_field_value(FieldType.MULTI_SELECT, ["a", "b"], ["z"]) is not None
    assert check_field_value(FieldType.MULTI_SELECT, ["a"], "a") is not None  # must be a list


def test_apply_defaults_fills_only_absent_keys():
    defs = [StubDef("priority", "high"), StubDef("size", 3), StubDef("no_default")]
    result = apply_defaults(defs, {"size": 5})
    # size supplied → kept; priority absent → seeded; no_default has none → skipped.
    assert result == {"size": 5, "priority": "high"}


def test_apply_defaults_preserves_explicit_none():
    # An explicit None is "leave it empty" — a default must not override it.
    defs = [StubDef("priority", "high")]
    assert apply_defaults(defs, {"priority": None}) == {"priority": None}


def test_apply_defaults_returns_new_dict():
    original = {"a": 1}
    defs = [StubDef("b", "x")]
    result = apply_defaults(defs, original)
    assert original == {"a": 1}  # caller's dict untouched
    assert result == {"a": 1, "b": "x"}
