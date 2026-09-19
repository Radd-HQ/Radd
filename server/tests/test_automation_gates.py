"""The named gates and the operator vocabulary they share (RADD-1265).

`gate.payload` ("Event value is") is the one open-ended gate — a dotted path, an
operator, a value — and it replaces the retired `gate.event` condition tree as
the escape hatch. `compare` and `_payload_path` are what give it meaning, so
the operator cases live here beside it.
"""

from radd.modules.automations.conditions import EventFacts, _change_name, compare, _payload_path
from radd.modules.automations.gates import (
    GATE_EVALUATORS,
    changed_by,
    field_changed,
    payload_value_is,
    state_category_is,
)
from radd.modules.automations.types import (
    TYPE_GATE_PAYLOAD,
    ConditionOperator,
)

ACTOR = {
    "actor_id": "11111111-1111-1111-1111-111111111111",
    "actor_email": "hussein@hjarrar.com",
    "actor_name": "Hussein Jarrar",
}


def facts(payload=None, **overrides):
    base = {"event_type": "item.updated", **ACTOR, "payload": payload or {}}
    base.update(overrides)
    return EventFacts(**base)


UPDATE_PAYLOAD = {
    # The canonical shape (RADD-922): everything about the ITEM is under `item`;
    # `changes` describes the EVENT and stays at the root.
    "item": {
        "id": "00000000-0000-0000-0000-0000000000aa",
        "key": "TD-1",
        "title": "a title",
        "state": {"name": "Done", "category": "done"},
        "labels": ["backend", "urgent"],
    },
    "changes": [
        {"field": "state", "from": "In Progress", "to": "Done"},
        {"field": "assignee", "from": None, "to": "Someone Else"},
    ],
}


def gate(path, operator, value=None, negate=False):
    return payload_value_is(facts(UPDATE_PAYLOAD), {"path": path, "operator": operator, "value": value, "negate": negate})


# --- the payload gate ---------------------------------------------------------


def test_the_payload_gate_is_registered_under_its_type():
    assert GATE_EVALUATORS[TYPE_GATE_PAYLOAD] is payload_value_is


def test_payload_path_with_list_fanout():
    assert gate("item.labels", "contains", "urgent")
    assert gate("item.state.name", "eq", "Done")
    assert gate("nope.deeper", "not_set")
    assert not gate("nope.deeper", "is_set")


def test_a_blank_path_or_a_missing_value_never_matches():
    """A half-filled form must not match everything — that is how an automation
    fires on events nobody meant to catch."""
    assert not gate("", "eq", "Done")
    assert not gate("item.state.name", "eq", "")
    assert not gate("item.state.name", "eq", None)
    assert not payload_value_is(facts(UPDATE_PAYLOAD), {"path": "item.state.name", "operator": "bogus", "value": "Done"})


def test_in_and_not_in_take_a_list_or_a_comma_separated_string():
    assert gate("item.state.name", "in", ["Done", "Canceled"])
    assert gate("item.state.name", "not_in", ["Todo", "Backlog"])
    assert gate("item.state.name", "in", "Done, Canceled")
    assert not gate("item.state.name", "in", "Todo")


def test_negate_inverts_the_answer():
    assert gate("item.state.name", "eq", "Done")
    assert not gate("item.state.name", "eq", "Done", negate=True)
    assert gate("item.state.name", "eq", "Todo", negate=True)


def test_matches_regex_and_numeric_compare():
    f = facts({"title": "PIPE-99 hotfix", "estimate_seconds": 3600})

    def check(op, path, value):
        return payload_value_is(f, {"path": path, "operator": op, "value": value})

    assert check("matches", "title", r"pipe-\d+")
    assert check("gt", "estimate_seconds", 1000)
    assert not check("lt", "estimate_seconds", 1000)
    # broken regex never matches (and never raises)
    assert not check("matches", "title", "([")


def test_changes_are_addressable_by_path():
    """`changes.field` fans out over the diff entries, so "did the state change"
    is expressible without the retired changed_field subject."""
    assert gate("changes.field", "contains", "state")
    assert gate("changes.to", "eq", "Done")
    assert not gate("changes.field", "contains", "priority")


# --- the operator vocabulary --------------------------------------------------


def test_compare_over_every_operator():
    assert compare(["a"], ConditionOperator.EQ, "A")
    assert compare([3], ConditionOperator.EQ, "3")
    assert compare(["a"], ConditionOperator.NEQ, "b")
    assert compare(["a", "b"], ConditionOperator.IN, ["b"])
    assert compare(["a"], ConditionOperator.NOT_IN, ["b", "c"])
    assert compare(["hotfix now"], ConditionOperator.CONTAINS, "fix")
    assert compare(["a", "b"], ConditionOperator.CONTAINS, "b")
    assert compare(["a"], ConditionOperator.NOT_CONTAINS, "z")
    assert compare(["x"], ConditionOperator.IS_SET, None)
    assert compare([], ConditionOperator.NOT_SET, None)
    assert compare([True], ConditionOperator.EQ, "true")


def test_payload_path_addresses_list_elements_not_the_list():
    payload = {"watchers": [{"name": "a"}, {"name": "b"}], "labels": ["x", "y"]}
    assert _payload_path(payload, "watchers.name") == ["a", "b"]
    assert _payload_path(payload, "labels") == ["x", "y"]
    assert _payload_path(payload, "missing.path") == []


# --- the named gates keep their exactness -------------------------------------


def test_state_category_reads_the_post_event_state():
    assert state_category_is(facts(UPDATE_PAYLOAD), {"categories": ["done"]})
    assert not state_category_is(facts(UPDATE_PAYLOAD), {"categories": ["in_progress"]})


def test_changed_by_matches_id_email_or_name():
    assert changed_by(facts(), {"users": ["hussein@hjarrar.com"]})
    assert changed_by(facts(), {"users": [ACTOR["actor_id"]]})
    assert not changed_by(facts(), {"users": ["someone@else.com"]})
    assert changed_by(facts(), {"users": ["someone@else.com"], "negate": True})


def test_field_changed_reads_the_transition_not_the_state():
    f = facts(UPDATE_PAYLOAD)
    assert field_changed(f, {"field": "state", "from_mode": "specific", "from_values": ["In Progress"], "to_mode": "specific", "to_values": ["Done"]})
    assert field_changed(f, {"field": "assignee", "from_mode": "empty", "to_mode": "any"})
    assert not field_changed(f, {"field": "priority"})
    assert not field_changed(f, {"field": ""})


def test_custom_field_diffs_are_named_by_key():
    assert _change_name({"field": "custom_field", "key": "severity", "name": "Severity"}) == "severity"
    assert _change_name({"field": "state"}) == "state"


def test_render_template_tokens():
    from radd.modules.automations.templating import render_template

    f = facts({"name": "PIPE - 118", "item": {"state": {"category": "done"}}, "labels": ["a", "b"]})
    out = render_template(
        "{{event_type}} on {{payload.name}} by {{actor.name}}: {{payload.labels}} {{nope}}",
        f,
        {"key": "TD-1", "title": "t"},
    )
    assert out == "item.updated on PIPE - 118 by Hussein Jarrar: a, b {{nope}}"
    assert render_template("{{item.key}}: {{item.title}}", f, {"key": "TD-1", "title": "t"}) == "TD-1: t"
    # no item context → item tokens stay verbatim
    assert render_template("{{item.key}}", f, None) == "{{item.key}}"
