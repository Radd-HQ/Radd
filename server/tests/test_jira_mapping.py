"""Field mapping for the import wizard (spec 90) — the pure suggestion +
validation logic, plus DB-backed plan CRUD.

The suggestions are what make the wizard usable (300 fields pre-filled, not
blank), and the validation is the guard that stops a bad mapping reaching the
importer — both worth pinning.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.exceptions import ConflictError
from radd.modules.fields.types import FieldType
from radd.modules.jiraimport import mapping
from radd.modules.jiraimport.mapping import FieldMapping, slug, suggest_mappings, validate_mappings
from radd.modules.jiraimport.schemas import FieldMappingEntry
from radd.modules.jiraimport.types import (
    BuiltinTarget,
    FieldAction,
    FieldBand,
    InferredField,
    InferredType,
)


def _field(jira_id, name, **kw) -> InferredField:
    return InferredField(
        jira_id=jira_id,
        name=name,
        inferred_type=kw.get("inferred_type", InferredType.TEXT),
        populated=kw.get("populated", 10),
        sample_count=10,
        is_builtin=kw.get("is_builtin", False),
        distinct_count=kw.get("distinct_count", 5),
        dominant_ratio=kw.get("dominant_ratio", 0.2),
        band=kw.get("band", FieldBand.IN_USE),
        schema_key=kw.get("schema_key", ""),
        distinct_values=kw.get("distinct_values"),
    )


# --- pure suggestion ---


def test_slug_produces_valid_field_keys():
    assert slug("Story Points") == "story_points"
    assert slug("Additional Traveler #") == "additional_traveler"
    assert slug("123 Numeric Lead") == "f_123_numeric_lead"
    assert slug("") == "field"
    assert len(slug("x" * 80)) == 50


def test_suggest_builtins_and_noise_are_not_mapped():
    fields = [
        _field("summary", "Summary", is_builtin=True),
        _field("customfield_1", "Rank", band=FieldBand.NOISE),
        _field("customfield_2", "Empty", populated=0, band=FieldBand.UNUSED),
    ]
    by_id = {m.jira_id: m for m in suggest_mappings(fields, set())}
    assert by_id["summary"].action is FieldAction.BUILTIN
    assert by_id["customfield_1"].action is FieldAction.IGNORE  # machinery
    # Spec 100: an UNUSED field is ignored by default and collapsed in the grid —
    # there is nothing to import, so it must not compete for attention.
    assert by_id["customfield_2"].action is FieldAction.IGNORE


def test_suggest_recognizes_epic_link_and_watchers_as_native():
    from radd.modules.jiraimport.types import BuiltinTarget

    fields = [
        _field("customfield_10008", "Epic Link", inferred_type=InferredType.TEXT),
        _field("customfield_12802", "Watchers", inferred_type=InferredType.USER),
        _field("customfield_10001", "Domain", inferred_type=InferredType.SELECT,
               distinct_values=["A", "B"]),
    ]
    by_id = {m.jira_id: m for m in suggest_mappings(fields, set())}
    # Epic Link → native parent (not a text field), Watchers → native watchers.
    assert by_id["customfield_10008"].action is FieldAction.NATIVE
    assert by_id["customfield_10008"].builtin_target is BuiltinTarget.PARENT
    assert by_id["customfield_12802"].action is FieldAction.NATIVE
    assert by_id["customfield_12802"].builtin_target is BuiltinTarget.WATCHERS
    # Domain is not auto-native (the admin picks Team if they want) — stays create.
    assert by_id["customfield_10001"].action is FieldAction.CREATE


def test_validate_native_needs_a_target():
    from radd.modules.jiraimport.types import BuiltinTarget

    good = [FieldMapping("j1", "Domain", FieldAction.NATIVE, builtin_target=BuiltinTarget.TEAM)]
    assert validate_mappings(good, {}) == []
    bad = [FieldMapping("j2", "Domain", FieldAction.NATIVE)]  # no builtin_target
    assert validate_mappings(bad, {})[0].jira_id == "j2"


def test_suggest_maps_to_existing_else_creates():
    fields = [
        # A neutral name on purpose: this covers SLUG-MATCHING, and a name that is
        # also a native concept would be claimed by the earlier native rule (see
        # test_a_native_concept_beats_a_matching_custom_field).
        _field("customfield_1", "Risk Level", inferred_type=InferredType.NUMBER),
        _field(
            "customfield_2", "Domain",
            inferred_type=InferredType.SELECT, distinct_values=["A", "B"],
        ),
    ]
    # risk_level already exists → map; domain doesn't → create with options.
    by_id = {m.jira_id: m for m in suggest_mappings(fields, {"risk_level"})}
    assert by_id["customfield_1"].action is FieldAction.MAP
    assert by_id["customfield_1"].target_key == "risk_level"
    create = by_id["customfield_2"]
    assert create.action is FieldAction.CREATE
    assert create.target_key == "domain" and create.create_type is FieldType.SELECT
    assert create.create_options == ["A", "B"]


# --- pure validation ---


def test_validate_catches_the_real_mistakes():
    existing = {"story_points": FieldType.NUMBER}
    bad = [
        FieldMapping("j1", "Maps to nothing", FieldAction.MAP, target_key="missing"),
        FieldMapping("j2", "Bad key", FieldAction.CREATE, target_key="Not A Key",
                     create_type=FieldType.TEXT),
        FieldMapping("j3", "Dup", FieldAction.CREATE, target_key="dupe", create_type=FieldType.TEXT),
        FieldMapping("j4", "Dup2", FieldAction.CREATE, target_key="dupe", create_type=FieldType.TEXT),
        FieldMapping("j5", "No opts", FieldAction.CREATE, target_key="sel",
                     create_type=FieldType.SELECT, create_options=None),
        FieldMapping("j6", "Clobber", FieldAction.CREATE, target_key="story_points",
                     create_type=FieldType.NUMBER),
    ]
    problems = {p.jira_id: p.message for p in validate_mappings(bad, existing)}
    assert "no custom field" in problems["j1"]
    assert "not a valid field key" in problems["j2"]
    assert "more than one field" in problems["j4"]  # dupe key
    assert "option set" in problems["j5"]
    assert "already exists" in problems["j6"]  # create over an existing field


def test_validate_passes_a_clean_set():
    existing = {"story_points": FieldType.NUMBER}
    good = [
        FieldMapping("j1", "Points", FieldAction.MAP, target_key="story_points"),
        FieldMapping("j2", "Domain", FieldAction.CREATE, target_key="domain",
                     create_type=FieldType.SELECT, create_options=["A", "B"]),
        FieldMapping("j3", "Skip", FieldAction.IGNORE),
        FieldMapping("j4", "Native", FieldAction.BUILTIN),
    ]
    assert validate_mappings(good, existing) == []


# --- DB-backed plan CRUD ---


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


def test_a_native_concept_beats_a_matching_custom_field():
    """Precedence, stated once: a field whose NAME is a native Radd concept is
    suggested as NATIVE even when a custom field of the same slug already exists.

    Story points are the case that forced the decision. Radd has a first-class
    `estimate_points` column (spec 70) that velocity, burndown and SLQ `points`
    read; routing Jira's points into a look-alike custom field would leave all
    three empty. The same rule already applied to Epic Link → PARENT. The grid is
    editable, so an admin who really wants the custom field changes that one row.
    """
    fields = [_field("customfield_1", "Story Points", inferred_type=InferredType.NUMBER)]

    (suggestion,) = suggest_mappings(fields, existing_keys={"story_points"})

    assert suggestion.action is FieldAction.NATIVE
    assert suggestion.builtin_target is BuiltinTarget.POINTS
