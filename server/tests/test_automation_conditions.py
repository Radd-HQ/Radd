"""Pure event-condition evaluator (spec 58) — the invariant every rule relies on."""

from radd.modules.automations.conditions import EventFacts, matches

ACTOR = {
    "actor_id": "11111111-1111-1111-1111-111111111111",
    "actor_email": "hussein@hjarrar.com",
    "actor_name": "Hussein Jarrar",
}


def facts(payload=None, **overrides):
    base = {"event_type": "item.updated", **ACTOR, "payload": payload or {}}
    base.update(overrides)
    return EventFacts(**base)


def cond(subject, operator, value=None, qualifier=None):
    node = {"subject": subject, "operator": operator}
    if value is not None:
        node["value"] = value
    if qualifier is not None:
        node["qualifier"] = qualifier
    return node


def group(op, *conditions):
    return {"op": op, "conditions": list(conditions)}


UPDATE_PAYLOAD = {
    "state": {"name": "Done", "category": "done"},
    "labels": ["backend", "urgent"],
    "changes": [
        {"field": "state", "from": "In Progress", "to": "Done"},
        {"field": "assignee", "from": None, "to": "Someone Else"},
    ],
}


# --- empty / trivial trees ---


def test_no_tree_always_matches():
    assert matches(facts(), None)
    assert matches(facts(), {})
    assert matches(facts(), {"op": "all", "conditions": []})


# --- subjects ---


def test_actor_matches_by_email_id_and_name():
    tree = group("all", cond("actor", "eq", "hussein@hjarrar.com"))
    assert matches(facts(), tree)
    tree = group("all", cond("actor", "eq", ACTOR["actor_id"]))
    assert matches(facts(), tree)
    tree = group("all", cond("actor", "eq", "someone@else.com"))
    assert not matches(facts(), tree)


def test_changed_field_membership():
    f = facts(UPDATE_PAYLOAD)
    assert matches(f, group("all", cond("changed_field", "contains", "state")))
    assert matches(f, group("all", cond("changed_field", "eq", "assignee")))
    assert not matches(f, group("all", cond("changed_field", "contains", "priority")))


def test_old_and_new_value_of_a_changed_field():
    f = facts(UPDATE_PAYLOAD)
    assert matches(f, group("all", cond("new_value", "eq", "Done", qualifier="state")))
    assert matches(f, group("all", cond("old_value", "eq", "in progress", qualifier="state")))
    # assignee went from unset -> set
    assert matches(f, group("all", cond("old_value", "not_set", qualifier="assignee")))
    assert matches(f, group("all", cond("new_value", "is_set", qualifier="assignee")))
    # a field that didn't change resolves to nothing
    assert matches(f, group("all", cond("new_value", "not_set", qualifier="priority")))
    assert not matches(f, group("all", cond("new_value", "eq", "high", qualifier="priority")))


def test_state_category_reads_the_post_event_state():
    assert matches(facts(UPDATE_PAYLOAD), group("all", cond("state_category", "eq", "done")))
    assert not matches(
        facts(UPDATE_PAYLOAD), group("all", cond("state_category", "eq", "in_progress"))
    )


def test_payload_path_with_list_fanout():
    f = facts(UPDATE_PAYLOAD)
    assert matches(f, group("all", cond("payload", "contains", "urgent", qualifier="labels")))
    assert matches(f, group("all", cond("payload", "eq", "Done", qualifier="state.name")))
    assert matches(f, group("all", cond("payload", "not_set", qualifier="nope.deeper")))


# --- operators ---


def test_in_and_not_in_lists():
    f = facts(UPDATE_PAYLOAD)
    assert matches(
        f, group("all", cond("new_value", "in", ["Done", "Canceled"], qualifier="state"))
    )
    assert matches(
        f, group("all", cond("new_value", "not_in", ["Todo", "Backlog"], qualifier="state"))
    )


def test_matches_regex_and_numeric_compare():
    f = facts({"title": "PIPE-99 hotfix", "estimate_seconds": 3600})
    assert matches(f, group("all", cond("payload", "matches", r"pipe-\d+", qualifier="title")))
    assert matches(f, group("all", cond("payload", "gt", 1000, qualifier="estimate_seconds")))
    assert not matches(f, group("all", cond("payload", "lt", 1000, qualifier="estimate_seconds")))
    # broken regex never matches (and never raises)
    assert not matches(f, group("all", cond("payload", "matches", "([", qualifier="title")))


# --- combinators ---


def test_nested_any_all_none():
    f = facts(UPDATE_PAYLOAD)
    tree = group(
        "all",
        cond("actor", "eq", "hussein@hjarrar.com"),
        group(
            "any",
            cond("new_value", "eq", "Blocked", qualifier="state"),
            cond("state_category", "eq", "done"),
        ),
        group("none", cond("changed_field", "contains", "priority")),
    )
    assert matches(f, tree)
    # flip the NONE group to something that did change -> whole tree fails
    tree["conditions"][2] = group("none", cond("changed_field", "contains", "state"))
    assert not matches(f, tree)


def test_label_diffs_resolve_added_and_removed():
    f = facts(
        {"changes": [{"field": "labels", "added": ["urgent"], "removed": ["backlog-groomed"]}]}
    )
    assert matches(f, group("all", cond("new_value", "eq", "urgent", qualifier="labels")))
    assert matches(
        f, group("all", cond("old_value", "eq", "backlog-groomed", qualifier="labels"))
    )
    assert not matches(f, group("all", cond("new_value", "eq", "backlog-groomed", qualifier="labels")))


def test_custom_field_diffs_match_by_key():
    f = facts(
        {
            "changes": [
                {"field": "custom_field", "key": "severity", "name": "Severity", "from": "s3", "to": "s1"}
            ]
        }
    )
    assert matches(f, group("all", cond("changed_field", "contains", "severity")))
    assert matches(f, group("all", cond("new_value", "eq", "s1", qualifier="severity")))
    assert matches(f, group("all", cond("old_value", "eq", "s3", qualifier="Severity")))


def test_render_template_tokens():
    from radd.modules.automations.templating import render_template

    f = facts({"name": "PIPE - 118", "state": {"category": "done"}, "labels": ["a", "b"]})
    out = render_template(
        "{{event_type}} on {{payload.name}} by {{actor.name}}: {{payload.labels}} {{nope}}",
        f,
        {"key": "TD-1", "title": "t"},
    )
    assert out == "item.updated on PIPE - 118 by Hussein Jarrar: a, b {{nope}}"
    assert render_template("{{item.key}}: {{item.title}}", f, {"key": "TD-1", "title": "t"}) == "TD-1: t"
    # no item context → item tokens stay verbatim
    assert render_template("{{item.key}}", f, None) == "{{item.key}}"


def test_depth_and_node_guards():
    deep = cond("actor", "is_set")
    for _ in range(10):
        deep = group("all", deep)
    assert not matches(facts(), deep)  # over MAX_DEPTH -> refuses to match
    wide = group("all", *[cond("actor", "is_set") for _ in range(60)])
    assert not matches(facts(), wide)  # over MAX_NODES -> refuses to match
