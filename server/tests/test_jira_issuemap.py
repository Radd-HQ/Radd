"""Jira issue JSON → Radd item draft (spec 90) — the pure translation.

Every decoding rule that could silently corrupt an import lives here: obfuscated
emails, status categories, priority/kind mapping, number preservation, mapped
custom-field value rendering (with select option filtering), comments/worklogs,
and issue-link typing.
"""

from radd.modules.fields.types import FieldType
from radd.modules.jiraimport import issuemap
from radd.modules.jiraimport.issuemap import (
    decode_email,
    person_email,
    render_value,
    to_utc_naive,
)
from radd.modules.jiraimport.schemas import FieldMappingEntry
from radd.modules.jiraimport.types import BuiltinTarget, FieldAction

# Spec 100: the domain for synthesizing an address Jira did not expose is supplied
# by the CALLER (the runner derives it from the connection's host). A neutral one
# here — the point of the change is that no domain is baked into the source.
DOMAIN = "example.com"


def map_issue(issue, mappings, catalog, **kwargs):
    """`issuemap.map_issue` with the domain the runner would pass."""
    kwargs.setdefault("fallback_domain", DOMAIN)
    return issuemap.map_issue(issue, mappings, catalog, **kwargs)


def test_decode_obfuscated_email():
    assert decode_email("proberts at example dot com") == "proberts@example.com"
    assert decode_email(None) is None
    assert decode_email("no-at-sign") is None


def test_person_email_falls_back_to_username():
    assert person_email({"emailAddress": "a at b dot com"}) == "a@b.com"
    # Spec 100: the domain is supplied by the caller (derived from the Jira host),
    # never baked into source. With no domain, nothing is invented.
    assert person_email({"name": "jsmith"}, "example.com") == "jsmith@example.com"
    assert person_email({"name": "jsmith"}) is None
    assert person_email({}) is None


def test_timestamp_normalizes_to_utc_naive():
    # Jira -0400 → UTC.
    assert to_utc_naive("2026-07-24T10:48:33.000-0400") == "2026-07-24T14:48:33"
    assert to_utc_naive(None) is None


def test_render_value_by_target_type():
    assert render_value({"value": "Red"}, FieldType.SELECT) == "Red"
    assert render_value([{"value": "A"}, {"value": "B"}], FieldType.MULTI_SELECT) == ["A", "B"]
    assert render_value("42", FieldType.NUMBER) == 42
    assert render_value("3.5", FieldType.NUMBER) == 3.5
    assert render_value("2026-07-24T10:00:00.000-0400", FieldType.DATE) == "2026-07-24"
    assert render_value(None, FieldType.TEXT) is None


def _issue(**fields):
    base = {"summary": "S", "issuetype": {"name": "Task"}, "status": {"name": "To Do", "statusCategory": {"key": "new"}}}
    base.update(fields)
    return {"key": "DEV-15885", "fields": base}


def test_map_issue_core_fields():
    issue = _issue(
        summary="Investigate the farm",
        priority={"name": "Major"},
        assignee={"emailAddress": "pierre at example dot com"},
        reporter={"name": "olmossa"},
        created="2026-07-24T10:48:33.000-0400",
        labels=["farm", "urgent"],
    )
    draft = map_issue(issue, [], {})
    assert draft.number == 15885 and draft.jira_key == "DEV-15885"
    assert draft.title == "Investigate the farm"
    assert draft.priority == "high"  # major → high
    assert draft.status_category == "todo"  # statusCategory new → todo
    assert draft.assignee_email == "pierre@example.com"
    assert draft.reporter_email == "olmossa@example.com"
    assert draft.created == "2026-07-24T14:48:33"
    assert draft.labels == ["farm", "urgent"]


def test_kind_and_canceled_category():
    assert map_issue(_issue(issuetype={"name": "Epic"}), [], {}).kind == "epic"
    assert map_issue(_issue(issuetype={"name": "Sub-task"}), [], {}).kind == "subtask"
    canceled = _issue(status={"name": "Cancelled", "statusCategory": {"key": "done"}})
    assert map_issue(canceled, [], {}).status_category == "canceled"


def test_mapped_custom_fields_render_and_filter_options():
    issue = _issue(
        customfield_1={"value": "Lisbon"},
        customfield_2=[{"value": "A"}, {"value": "ZZZ"}],  # ZZZ not in options → dropped
        customfield_3="free text",
    )
    mappings = [
        FieldMappingEntry(jira_id="customfield_1", action=FieldAction.CREATE, target_key="site",
                          create_type=FieldType.SELECT, create_options=["Lisbon", "Prague"]),
        FieldMappingEntry(jira_id="customfield_2", action=FieldAction.CREATE, target_key="domain",
                          create_type=FieldType.MULTI_SELECT, create_options=["A", "B"]),
        FieldMappingEntry(jira_id="customfield_3", action=FieldAction.MAP, target_key="notes"),
    ]
    catalog = {"notes": FieldType.TEXT}
    draft = map_issue(issue, mappings, catalog)
    assert draft.custom_fields["site"] == "Lisbon"
    assert draft.custom_fields["domain"] == ["A"]  # ZZZ filtered out
    assert draft.custom_fields["notes"] == "free text"


def test_out_of_option_scalar_is_dropped():
    issue = _issue(customfield_1={"value": "Unknown"})
    mappings = [
        FieldMappingEntry(jira_id="customfield_1", action=FieldAction.CREATE, target_key="site",
                          create_type=FieldType.SELECT, create_options=["Lisbon"]),
    ]
    draft = map_issue(issue, mappings, {})
    assert "site" not in draft.custom_fields


def test_parent_epic_comments_worklogs_links():
    issue = _issue(
        parent={"key": "DEV-100"},
        comment={"comments": [
            {"body": "*bold* note", "author": {"name": "jsmith"}, "created": "2026-01-01T00:00:00.000+0000"},
        ]},
        worklog={"worklogs": [
            {"timeSpent": "2h", "started": "2026-01-02T09:00:00.000+0000", "author": {"name": "jsmith"}, "comment": "did stuff"},
        ]},
        issuelinks=[
            {"type": {"name": "Blocks"}, "outwardIssue": {"key": "DEV-200"}},
            {"type": {"name": "Cloners"}, "inwardIssue": {"key": "DEV-300"}},
        ],
    )
    draft = map_issue(issue, [], {})
    assert draft.parent_jira_key == "DEV-100"
    assert draft.comments[0].body == "**bold** note" and draft.comments[0].author_email == "jsmith@example.com"
    assert draft.worklogs[0].time_spent == "2h" and draft.worklogs[0].worked_on == "2026-01-02"
    assert draft.links[0].target_key == "DEV-200" and draft.links[0].link_type == "blocks"
    assert draft.links[1].target_key == "DEV-300" and draft.links[1].link_type == "duplicates"


def test_epic_link_field_becomes_parent_when_no_subtask_parent():
    issue = _issue(customfield_10008="DEV-500")
    draft = map_issue(issue, [], {}, epic_link_field="customfield_10008")
    assert draft.parent_jira_key is None and draft.epic_jira_key == "DEV-500"


def test_jira_number_extraction():
    assert issuemap.jira_number("DEV-15885") == 15885
    assert issuemap.jira_number("TD-1") == 1


# --- native-target mappings (spec 90 follow-up) ---

from radd.modules.jiraimport.types import BuiltinTarget  # noqa: E402


def _native(jira_id, target):
    return FieldMappingEntry(jira_id=jira_id, action=FieldAction.NATIVE, builtin_target=target)


def test_native_team_and_watchers_and_dates():
    issue = _issue(
        customfield_domain={"value": "CFX"},
        customfield_watchers=[{"name": "olmossa"}, {"emailAddress": "a at b dot com"}],
        customfield_start="2026-02-01T00:00:00.000+0000",
    )
    mappings = [
        _native("customfield_domain", BuiltinTarget.TEAM),
        _native("customfield_watchers", BuiltinTarget.WATCHERS),
        _native("customfield_start", BuiltinTarget.START_DATE),
    ]
    draft = map_issue(issue, mappings, {})
    assert draft.native_team == "CFX"
    assert draft.native_watcher_emails == ["olmossa@example.com", "a@b.com"]
    assert draft.start_date == "2026-02-01"
    # A native-mapped field is NOT also written as a custom field.
    assert "customfield_domain" not in draft.custom_fields


def test_native_parent_maps_the_epic_key_without_a_text_field():
    issue = _issue(customfield_epic="DEV-500")
    draft = map_issue(issue, [_native("customfield_epic", BuiltinTarget.PARENT)], {})
    # Routed to the parent relationship (resolved second-pass), not a custom field.
    assert draft.epic_jira_key == "DEV-500" and draft.parent_jira_key == "DEV-500"
    assert draft.custom_fields == {}


def test_value_map_translates_team_and_status_and_options():
    issue = _issue(
        customfield_level={"value": "L1"},
        status={"name": "In Review", "statusCategory": {"key": "indeterminate"}},
        customfield_sev={"value": "P1"},
    )
    mappings = [
        # Sysadmin level → a specific team name (create-on-the-fly happens in the runner).
        FieldMappingEntry(jira_id="customfield_level", action=FieldAction.NATIVE,
                          builtin_target=BuiltinTarget.TEAM, value_map={"L1": "Support Tier 1"}),
        # A Jira status → a Radd state name.
        FieldMappingEntry(jira_id="status", action=FieldAction.NATIVE,
                          builtin_target=BuiltinTarget.STATUS, value_map={"In Review": "Code Review"}),
        # A select custom field → renamed options.
        FieldMappingEntry(jira_id="customfield_sev", action=FieldAction.CREATE, target_key="severity",
                          create_type=FieldType.SELECT, create_options=["P1"],
                          value_map={"P1": "Critical"}),
    ]
    draft = map_issue(issue, mappings, {})
    assert draft.native_team == "Support Tier 1"  # translated, not "L1"
    assert draft.native_status_name == "Code Review"
    # The severity value was remapped P1 → Critical (and Critical is in the options
    # since the runner rebuilds options from value_map targets).
    assert draft.custom_fields["severity"] == "Critical"


def test_unmapped_team_value_passes_through_status_falls_back():
    issue = _issue(
        customfield_level={"value": "L9"},  # not in the value_map
        status={"name": "Weird", "statusCategory": {"key": "new"}},
    )
    mappings = [
        FieldMappingEntry(jira_id="customfield_level", action=FieldAction.NATIVE,
                          builtin_target=BuiltinTarget.TEAM, value_map={"L1": "Tier 1"}),
        FieldMappingEntry(jira_id="status", action=FieldAction.NATIVE,
                          builtin_target=BuiltinTarget.STATUS, value_map={"In Review": "Code Review"}),
    ]
    draft = map_issue(issue, mappings, {})
    assert draft.native_team == "L9"  # unmapped → the value itself becomes the team
    assert draft.native_status_name is None  # unmapped status → category fallback


def test_native_cycle_extracts_sprint_name_not_the_bean_blob():
    # The Sprint field is a list of agile bean toString blobs — the cycle must be
    # the sprint NAME, never the whole blob (the >200-char bug).
    bean = ("com.atlassian.greenhopper.service.sprint.Sprint@1c47d991[id=979,"
            "rapidViewId=196,state=ACTIVE,name=PIPE - 116,startDate=2026-07-12T03:51,"
            "endDate=2026-07-25T15:50,completeDate=<null>,sequence=975,goal=]")
    issue = _issue(customfield_10002=[bean])
    m = FieldMappingEntry(jira_id="customfield_10002", action=FieldAction.NATIVE,
                          builtin_target=BuiltinTarget.CYCLE)
    draft = map_issue(issue, [m], {})
    assert "PIPE - 116" in draft.sprint_names
    assert all(len(n) < 100 for n in draft.sprint_names)  # never the blob


def test_scalar_never_stringifies_a_list():
    # Regression: _scalar on a list took str(list) → a Python repr. Now it takes
    # the first element's scalar.
    assert issuemap._scalar(["A", "B"]) == "A"
    assert issuemap._scalar([{"value": "X"}]) == "X"
    assert issuemap._scalar([]) is None


def test_sprint_beans_carry_dates_state_and_completion():
    # ALL of an issue's sprints come through (its cycle history), each with the dates
    # + completion needed to import a cycle with the RIGHT status.
    closed = ("com.atlassian.greenhopper.service.sprint.Sprint@1[id=1,state=CLOSED,"
              "name=PIPE - 114,startDate=2026-06-01T03:51,endDate=2026-06-14T15:50,"
              "completeDate=2026-06-15T10:00:00.000-0400,sequence=1,goal=]")
    active = ("com.atlassian.greenhopper.service.sprint.Sprint@2[id=2,state=ACTIVE,"
              "name=PIPE - 116,startDate=2026-07-12T03:51,endDate=2026-07-25T15:50,"
              "completeDate=<null>,goal=]")
    sprints = issuemap._sprints_from([closed, active])
    assert [s.name for s in sprints] == ["PIPE - 114", "PIPE - 116"]  # previous first, current last
    assert sprints[0].state == "closed" and sprints[0].complete_date == "2026-06-15"
    assert sprints[0].start_date == "2026-06-01" and sprints[0].end_date == "2026-06-14"
    assert sprints[1].state == "active" and sprints[1].complete_date is None


def test_sprint_dicts_and_scalar_fallback():
    # Newer Jira returns dicts; a bare string falls back to a bare name.
    dicts = issuemap._sprints_from(
        [{"name": "PIPE - 200", "state": "future", "startDate": None, "endDate": None}]
    )
    assert dicts[0].name == "PIPE - 200" and dicts[0].state == "future"
    assert dicts[0].start_date is None
    scalar = issuemap._sprints_from("PIPE - 300")
    assert scalar[0].name == "PIPE - 300" and scalar[0].state is None


def test_issue_link_direction_marks_inward_vs_outward():
    # A Jira link is directional: this issue's OUTWARD link is this→other, its
    # INWARD link is other→this. The draft records which, so the runner can keep
    # the direction right instead of always writing this→other.
    issue = _issue(issuelinks=[
        {"type": {"name": "Blocks"}, "inwardIssue": {"key": "DEV-1"}},   # this is blocked by DEV-1
        {"type": {"name": "Blocks"}, "outwardIssue": {"key": "DEV-3"}},  # this blocks DEV-3
    ])
    draft = map_issue(issue, [], {})
    inward = next(link for link in draft.links if link.target_key == "DEV-1")
    outward = next(link for link in draft.links if link.target_key == "DEV-3")
    assert inward.inward is True and inward.link_type == "blocks"
    assert outward.inward is False and outward.link_type == "blocks"


def test_native_priority_and_labels():
    issue = _issue(
        customfield_sev={"value": "Blocker"},
        customfield_tags=[{"value": "farm"}, {"value": "urgent"}],
    )
    draft = map_issue(
        issue,
        [
            _native("customfield_sev", BuiltinTarget.PRIORITY),
            _native("customfield_tags", BuiltinTarget.LABELS),
        ],
        {},
    )
    assert draft.priority == "blocker"
    assert "farm" in draft.labels and "urgent" in draft.labels


# --- story points → Radd's own column, not a custom field (spec 70) ---


def _points_mapping(jira_id="customfield_10002"):
    return [FieldMappingEntry(
        jira_id=jira_id, jira_name="Story Points",
        action=FieldAction.NATIVE, builtin_target=BuiltinTarget.POINTS,
    )]


def test_story_points_map_into_estimate_points():
    """Jira ships story points as a CUSTOM field, so without a native target it
    could only ever become a generic number field — never the column velocity,
    burndown and SLQ `points` actually read."""
    issue = {"key": "SP-1", "fields": {"summary": "Estimated", "customfield_10002": 5}}
    draft = map_issue(issue, _points_mapping(), {})
    assert draft.estimate_points == 5.0


def test_story_points_accept_a_string_and_a_decimal():
    """A hand-rebuilt points field can arrive as text rather than a JSON number."""
    for raw, expected in (("3", 3.0), ("3.5", 3.5), (0, 0.0), (0.5, 0.5)):
        issue = {"key": "SP-2", "fields": {"summary": "x", "customfield_10002": raw}}
        assert map_issue(issue, _points_mapping(), {}).estimate_points == expected


def test_unestimated_and_junk_points_stay_none():
    """None means unestimated. It must never become 0, which is a real estimate."""
    for raw in (None, "", "   ", "abc", {}, []):
        issue = {"key": "SP-3", "fields": {"summary": "x", "customfield_10002": raw}}
        assert map_issue(issue, _points_mapping(), {}).estimate_points is None


def test_out_of_range_points_are_dropped_not_clamped():
    """ItemCreate bounds points 0-999. Clamping an 8000 to 999 would invent an
    estimate nobody made, and would fail the import row silently if it didn't."""
    for raw in (8000, -1, 1000):
        issue = {"key": "SP-4", "fields": {"summary": "x", "customfield_10002": raw}}
        assert map_issue(issue, _points_mapping(), {}).estimate_points is None


def test_story_points_are_suggested_natively_by_name():
    """The Jira field is literally called "Story Points" — the wizard should
    propose the native target rather than making the admin find it."""
    from radd.modules.jiraimport import mapping
    from radd.modules.jiraimport.types import InferredField, InferredType

    for name in ("Story Points", "story point estimate", "Points"):
        field = InferredField(
            jira_id="customfield_10002", name=name, inferred_type=InferredType.NUMBER,
            populated=10, sample_count=10, is_builtin=False,
        )
        (suggestion,) = mapping.suggest_mappings([field], existing_keys=set())
        assert suggestion.action is FieldAction.NATIVE, name
        assert suggestion.builtin_target is BuiltinTarget.POINTS, name
