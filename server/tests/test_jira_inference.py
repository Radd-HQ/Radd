"""Inferring an inbound schema from a Jira JQL sample (spec 90).

The inference is pure, so this is where its judgement is pinned: the Jira field
catalog is authoritative for type (a `string` stays text even on a tiny sample
where it looks low-cardinality), built-in fields are flagged not dropped, and
select option sets are only offered when they are actually bounded.
"""

from collections import Counter

from radd.modules.jiraimport import inference
from radd.modules.jiraimport.inference import classify
from radd.modules.jiraimport.types import FieldBand, InferredType


CATALOG = {
    "customfield_10001": {"name": "Team", "schema_type": "option", "is_custom": True},
    "customfield_10002": {"name": "Notes", "schema_type": "string", "is_custom": True},
    "customfield_10003": {"name": "Story Points", "schema_type": "number", "is_custom": True},
    "customfield_10004": {
        "name": "Components",
        "schema_type": "array",
        "schema_items": "option",
        "is_custom": True,
    },
    "labels": {"name": "Labels", "schema_type": "array", "schema_items": "string", "is_custom": False},
    "summary": {"name": "Summary", "schema_type": "string", "is_custom": False},
    "priority": {"name": "Priority", "schema_type": "priority", "is_custom": False},
}


def _issue(**fields):
    return {"fields": fields}


def test_catalog_type_beats_sample_cardinality():
    # Notes is a string; even though the tiny sample has few distinct values, it
    # must NOT be offered as a select.
    issues = [
        _issue(customfield_10002="short note"),
        _issue(customfield_10002="another"),
    ]
    fields = {f.jira_id: f for f in inference.infer_schema(issues, CATALOG)}
    assert fields["customfield_10002"].inferred_type is InferredType.TEXT
    assert fields["customfield_10002"].distinct_values is None


def test_option_field_becomes_select_with_its_values():
    issues = [
        _issue(customfield_10001={"value": "Platform"}),
        _issue(customfield_10001={"value": "Pipeline"}),
        _issue(customfield_10001={"value": "Platform"}),
    ]
    field = {f.jira_id: f for f in inference.infer_schema(issues, CATALOG)}["customfield_10001"]
    assert field.inferred_type is InferredType.SELECT
    assert field.distinct_values == ["Pipeline", "Platform"]
    assert field.populated == 3 and field.populate_rate == 1.0


def test_array_of_options_is_multi_select_labels_are_text():
    issues = [
        _issue(customfield_10004=[{"value": "A"}, {"value": "B"}], labels=["x", "y", "z"]),
    ]
    fields = {f.jira_id: f for f in inference.infer_schema(issues, CATALOG)}
    assert fields["customfield_10004"].inferred_type is InferredType.MULTI_SELECT
    assert fields["customfield_10004"].distinct_values == ["A", "B"]
    # labels is a high-cardinality string array → text, not a select.
    assert fields["labels"].inferred_type is InferredType.TEXT


def test_builtin_fields_are_flagged_not_dropped():
    issues = [_issue(summary="Hi", priority={"name": "High"})]
    fields = {f.jira_id: f for f in inference.infer_schema(issues, CATALOG)}
    assert fields["summary"].is_builtin and fields["priority"].is_builtin
    # A custom field of the same populate rate sorts ABOVE built-ins.
    assert not fields["customfield_10003"].is_builtin if "customfield_10003" in fields else True


def test_number_and_populate_rate():
    issues = [
        _issue(customfield_10003=5),
        _issue(customfield_10003=None),
        _issue(),
    ]
    field = {f.jira_id: f for f in inference.infer_schema(issues, CATALOG)}["customfield_10003"]
    assert field.inferred_type is InferredType.NUMBER
    assert field.populated == 1 and field.sample_count == 3
    assert abs(field.populate_rate - 1 / 3) < 1e-9


def test_custom_fields_sort_before_builtins_by_population():
    issues = [
        _issue(summary="s", customfield_10001={"value": "X"}, customfield_10003=1),
        _issue(summary="t", customfield_10001={"value": "Y"}),
    ]
    ordered = [f.jira_id for f in inference.infer_schema(issues, CATALOG)]
    # customfield_10001 (2/2) before customfield_10003 (1/2) before any builtin.
    assert ordered.index("customfield_10001") < ordered.index("customfield_10003")
    assert ordered.index("customfield_10003") < ordered.index("summary")


def test_constant_default_field_is_flagged_noise():
    # A select where every sampled issue has the same value ("No") — an org-wide
    # default, not real data. Flagged so the wizard collapses it.
    issues = [_issue(customfield_10001={"value": "No"}) for _ in range(10)]
    catalog = {"customfield_10001": {"name": "Accommodation", "schema_type": "option", "is_custom": True}}
    field = inference.infer_schema(issues, catalog)[0]
    assert field.populate_rate == 1.0
    assert field.dominant_ratio == 1.0
    assert field.band is FieldBand.NOISE


def test_varied_field_is_not_noise():
    issues = [_issue(customfield_10001={"value": v}) for v in ("A", "B", "C", "A", "D")]
    catalog = {"customfield_10001": {"name": "Domain", "schema_type": "option", "is_custom": True}}
    field = inference.infer_schema(issues, catalog)[0]
    assert field.distinct_count == 4 and field.dominant_ratio == 2 / 5
    assert field.band is FieldBand.IN_USE


# --- spec 100: noise is identified by Jira's stable type key, never by id/name ---

RANK = "com.pyxis.greenhopper.jira:gh-lexo-rank"
DEVSUMMARY = "com.atlassian.jira.plugins.jira-development-integration-plugin:devsummary"


def test_machinery_is_flagged_by_its_jira_type_key_even_when_every_value_differs():
    """The case the data-shape heuristic CANNOT catch, and the reason type keys
    matter: a board rank is different on every issue, so it looks like the richest
    field in the project. Spec 90 could only exclude it by hardcoding its id."""
    issues = [_issue(customfield_777=f"0|abc{n}:", customfield_888="{blob}") for n in range(20)]
    catalog = {
        "customfield_777": {"name": "Queue Order", "schema_type": "string",
                            "schema_key": RANK, "is_custom": True},
        "customfield_888": {"name": "Development", "schema_type": "string",
                            "schema_key": DEVSUMMARY, "is_custom": True},
    }
    fields = {f.jira_id: f for f in inference.infer_schema(issues, catalog)}
    assert fields["customfield_777"].band is FieldBand.NOISE
    assert "ordering key" in fields["customfield_777"].band_reason
    assert fields["customfield_888"].band is FieldBand.NOISE


def test_a_field_id_spec_90_blacklisted_is_ordinary_data_on_another_instance():
    """THE de-hardcoding proof. `customfield_10002` was hardcoded as noise (it was
    Sprint on one instance); elsewhere the same id is a normal field, and must be
    offered for mapping like any other."""
    issues = [_issue(customfield_10002=v) for v in ("Alpha", "Beta", "Gamma", "Delta")]
    catalog = {
        "customfield_10002": {"name": "Customer", "schema_type": "option", "is_custom": True}
    }
    field = inference.infer_schema(issues, catalog)[0]
    assert field.band is FieldBand.IN_USE
    assert field.band_reason == ""


def test_the_sprint_field_is_found_by_type_key_whatever_its_id():
    """Spec 90 read `customfield_10002` unconditionally. Jira Cloud commonly uses
    customfield_10020, and on DC it is arbitrary."""
    from radd.modules.jiraimport import schemakeys
    from radd.modules.jiraimport.types import BuiltinTarget

    catalog = {
        "customfield_10020": {"name": "Sprint", "schema_type": "array",
                              "schema_key": schemakeys.JiraSchemaKey.SPRINT.value,
                              "is_custom": True},
    }
    assert schemakeys.find_by_schema_key(catalog, schemakeys.JiraSchemaKey.SPRINT) == [
        "customfield_10020"
    ]
    field = inference.infer_schema([_issue(customfield_10020=["x"])], catalog)[0]
    assert field.native_target is BuiltinTarget.CYCLE


def test_several_fields_can_share_one_type_key():
    """A live instance carried TWO gh-lexo-rank fields, "Rank" and "Queue Order" —
    which a single hardcoded id could never have covered."""
    from radd.modules.jiraimport import schemakeys

    catalog = {
        "customfield_10007": {"name": "Rank", "schema_key": RANK},
        "customfield_13701": {"name": "Queue Order", "schema_key": RANK},
        "customfield_1": {"name": "Notes", "schema_key": ""},
    }
    assert schemakeys.find_by_schema_key(catalog, RANK) == [
        "customfield_13701",
        "customfield_10007",
    ][::-1]


def test_a_field_nothing_fills_in_is_unused_and_says_so():
    """Spec 100. Spec 90 had no way to express "unused": such a field scored as
    ordinary data and sat at the TOP of the mapping grid. On a real instance that
    is most of the catalog — 337 fields, a couple of dozen with anything in them."""
    issues = [_issue(customfield_1=f"value {n}") for n in range(4)]
    catalog = {
        "customfield_1": {"name": "Used", "schema_type": "string", "is_custom": True},
        "customfield_2": {"name": "Never Filled In", "schema_type": "string", "is_custom": True},
    }
    # A catalog field no issue carries still appears — hidden, not dropped.
    issues[0]["fields"]["customfield_2"] = None
    fields = {f.jira_id: f for f in inference.infer_schema(issues, catalog)}
    empty = fields["customfield_2"]
    assert empty.band is FieldBand.UNUSED
    assert empty.ignored_by_default is True
    # The reason names the evidence, so "unused" over a SAMPLE cannot be mistaken
    # for "unused" over a whole snapshot.
    assert empty.band_reason == "no values on any of the 4 issues"
    assert fields["customfield_1"].band is FieldBand.IN_USE


def test_fields_that_carry_data_sort_above_machinery_above_empties():
    """The grid opens on what matters: in-use, then machinery, then the empties,
    then the columns Jira handles natively."""
    issues = [_issue(cf_used={"value": v}, cf_rank=f"0|x{v}:", summary=f"s{v}") for v in "ABC"]
    issues[0]["fields"]["cf_empty"] = None
    catalog = {
        "cf_used": {"name": "Domain", "schema_type": "option", "is_custom": True},
        "cf_rank": {"name": "Rank", "schema_type": "string", "schema_key": RANK, "is_custom": True},
        "cf_empty": {"name": "Unused", "schema_type": "string", "is_custom": True},
        "summary": {"name": "Summary", "schema_type": "string"},
    }
    order = [f.jira_id for f in inference.infer_schema(issues, catalog)]
    assert order == ["cf_used", "cf_rank", "cf_empty", "summary"]


def test_a_near_constant_field_is_flagged_from_the_data_itself():
    """The other instance-independent signal: an org-wide default applied to every
    issue is not ticket data, whatever it is called."""
    issues = [_issue(customfield_5="Standard") for _ in range(19)] + [_issue(customfield_5="Other")]
    catalog = {"customfield_5": {"name": "Travel Policy", "schema_type": "option", "is_custom": True}}
    field = inference.infer_schema(issues, catalog)[0]
    assert field.band is FieldBand.NOISE
    assert "same value" in field.band_reason


def test_useful_fields_sort_above_noise_and_builtins():
    issues = [
        _issue(
            customfield_10001={"value": v},  # varied → useful
            customfield_13400="blob",  # noise, by its Jira type key
            summary=f"s{v}",  # builtin
        )
        for v in ("A", "B", "C")
    ]
    catalog = {
        "customfield_10001": {"name": "Domain", "schema_type": "option", "is_custom": True},
        "customfield_13400": {"name": "Development", "schema_type": "string",
                              "schema_key": DEVSUMMARY, "is_custom": True},
        "summary": {"name": "Summary", "schema_type": "string"},
    }
    order = [f.jira_id for f in inference.infer_schema(issues, catalog)]
    assert order.index("customfield_10001") < order.index("customfield_13400")
    assert order.index("customfield_13400") < order.index("summary")


def test_option_sets_replace_sampled_values():
    from radd.modules.jiraimport.service import _apply_option_sets
    from radd.modules.jiraimport.types import InferredType

    # The sample only saw two Domain values; the field spec has more.
    issues = [_issue(customfield_10001={"value": "CFX"}), _issue(customfield_10001={"value": "FX"})]
    catalog = {"customfield_10001": {"name": "Domain", "schema_type": "option", "is_custom": True}}
    fields = inference.infer_schema(issues, catalog)
    _apply_option_sets(fields, {"customfield_10001": ["Assets", "CFX", "FX", "Lighting", "Production"]})
    domain = {f.jira_id: f for f in fields}["customfield_10001"]
    # The full configured set is now offered (union with anything sampled).
    assert domain.distinct_values == ["Assets", "CFX", "FX", "Lighting", "Production"]
    assert domain.inferred_type is InferredType.SELECT


def test_option_sets_promote_a_text_looking_field_to_select():
    from radd.modules.jiraimport.service import _apply_option_sets
    from radd.modules.jiraimport.types import InferredType

    # A field the sample thought was text, but the spec says it has options.
    issues = [_issue(customfield_10002="Lisbon")]
    catalog = {"customfield_10002": {"name": "Site", "schema_type": "string", "is_custom": True}}
    fields = inference.infer_schema(issues, catalog)
    assert fields[0].inferred_type is InferredType.TEXT  # before
    _apply_option_sets(fields, {"customfield_10002": ["Lisbon", "Prague", "Oslo"]})
    assert fields[0].inferred_type is InferredType.SELECT  # after
    assert fields[0].distinct_values == ["Lisbon", "Oslo", "Prague"]


def test_classify_fallbacks_without_a_catalog_type():
    # No schema type: cardinality is the only signal.
    assert classify("", "", False, Counter({"a": 3, "b": 2})) is InferredType.SELECT
    assert classify("", "", False, Counter()) is InferredType.UNKNOWN
    many = Counter({str(i): 1 for i in range(inference.SELECT_MAX_DISTINCT + 5)})
    assert classify("", "", False, many) is InferredType.TEXT
