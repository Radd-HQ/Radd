"""Jira's own stable field-type keys (spec 100) — how the importer stops being
hardcoded to one Jira.

Every custom field in Jira's `/field` catalog carries `schema.custom`: the type
key of the plugin that defines it, e.g. `com.pyxis.greenhopper.jira:gh-sprint`.
Unlike a field ID, that key is IDENTICAL on every Jira instance on earth. Spec 90
threw it away and identified fields by literal ID instead, which is how the
importer ended up with:

    NOISE_JIRA_FIELDS = {"customfield_10002", "customfield_13400", "customfield_10007",
                         "customfield_10009", "customfield_13701", "customfield_51604"}
    def sprints(fields): return _sprints_from(fields.get("customfield_10002"))

Both are replaced by lookups through this table. Checked against a live Jira DC
instance on 2026-07-28: `gh-sprint` → customfield_10002, `gh-epic-link` →
customfield_10003, `gh-lexo-rank` → customfield_10007 AND customfield_13701,
`devsummary` → customfield_13400 — i.e. every ID that list hardcoded, discovered
rather than assumed. (customfield_51604 was not present at all: the hardcoded
list had already gone stale against the very instance it was written for.)

Identification here is a SUGGESTION, never a silent decision. Everything it finds
is shown in the mapping step with the reason, and can be overridden — a field
this table has never heard of is an unknown to be mapped by hand, not a failure.
"""

from __future__ import annotations

from enum import StrEnum

from .types import BuiltinTarget


class JiraSchemaKey(StrEnum):
    """`schema.custom` values worth recognising. Instance-independent by design."""

    # Jira Software (Greenhopper) — agile.
    SPRINT = "com.pyxis.greenhopper.jira:gh-sprint"
    EPIC_LINK = "com.pyxis.greenhopper.jira:gh-epic-link"
    EPIC_NAME = "com.pyxis.greenhopper.jira:gh-epic-label"
    EPIC_STATUS = "com.pyxis.greenhopper.jira:gh-epic-status"
    EPIC_COLOUR = "com.pyxis.greenhopper.jira:gh-epic-color"
    LEXO_RANK = "com.pyxis.greenhopper.jira:gh-lexo-rank"
    GLOBAL_RANK = "com.pyxis.greenhopper.jira:gh-global-rank"
    STORY_POINTS = "com.pyxis.greenhopper.jira:jsw-story-points"  # Jira Cloud
    # Advanced Roadmaps / Portfolio.
    PARENT_LINK = "com.atlassian.jpo:jpo-custom-field-parent"
    TEAM = "com.atlassian.teams:rm-teams-custom-field-team"
    # Development panel — a JSON blob about branches and commits, never data.
    DEV_SUMMARY = (
        "com.atlassian.jira.plugins.jira-development-integration-plugin:devsummary"
    )
    # Jira Service Management request metadata.
    REQUEST_TYPE = "com.atlassian.servicedesk:vp-origin"
    REQUEST_PARTICIPANTS = "com.atlassian.servicedesk:sd-request-participants"


# A field whose type key is here drives a NATIVE Radd concept rather than becoming
# a custom field. Pre-selected in the mapping step, with the reason shown.
NATIVE_BY_SCHEMA_KEY: dict[str, BuiltinTarget] = {
    JiraSchemaKey.SPRINT.value: BuiltinTarget.CYCLE,
    JiraSchemaKey.EPIC_LINK.value: BuiltinTarget.PARENT,
    JiraSchemaKey.PARENT_LINK.value: BuiltinTarget.PARENT,
    JiraSchemaKey.STORY_POINTS.value: BuiltinTarget.POINTS,
    JiraSchemaKey.TEAM.value: BuiltinTarget.TEAM,
    JiraSchemaKey.REQUEST_PARTICIPANTS.value: BuiltinTarget.WATCHERS,
}

# Type keys that are pure machinery: board ordering, the dev-panel blob, colour
# swatches. Collapsed by default in the mapping step — visible, with the reason,
# and overridable. Spec 90 hid these behind a blocklist of literal IDs, so on any
# other instance it hid the wrong fields and showed the noise.
NOISE_SCHEMA_KEYS: frozenset[str] = frozenset(
    {
        JiraSchemaKey.LEXO_RANK.value,
        JiraSchemaKey.GLOBAL_RANK.value,
        JiraSchemaKey.DEV_SUMMARY.value,
        JiraSchemaKey.EPIC_COLOUR.value,
        JiraSchemaKey.EPIC_STATUS.value,
    }
)

# Why a field was flagged, in words the mapping step shows verbatim. A reason the
# admin can read is what makes overriding it a decision rather than a guess.
NOISE_REASONS: dict[str, str] = {
    JiraSchemaKey.LEXO_RANK.value: "Jira board ordering key — position data, not ticket data",
    JiraSchemaKey.GLOBAL_RANK.value: "Jira board ordering key — position data, not ticket data",
    JiraSchemaKey.DEV_SUMMARY.value: "the development panel's internal JSON blob",
    JiraSchemaKey.EPIC_COLOUR.value: "the colour swatch Jira draws epics with",
    JiraSchemaKey.EPIC_STATUS.value: "Jira's legacy epic status, superseded by the workflow",
}

# Story Points is a plain number field on Jira DC with no distinguishing type key,
# so it can only be found by name there. Cloud has `jsw-story-points`, which is
# checked first. A name match is a suggestion like any other.
STORY_POINT_NAMES: frozenset[str] = frozenset(
    {"story points", "story point estimate", "points", "storypoints"}
)


def native_target(schema_key: str, name: str) -> BuiltinTarget | None:
    """The native Radd concept a field feeds, by type key first and name second."""
    if schema_key and schema_key in NATIVE_BY_SCHEMA_KEY:
        return NATIVE_BY_SCHEMA_KEY[schema_key]
    if name.strip().lower() in STORY_POINT_NAMES:
        return BuiltinTarget.POINTS
    return None


def noise_reason(schema_key: str) -> str:
    """Why this field is machinery, or "" if it is not."""
    return NOISE_REASONS.get(schema_key, "") if schema_key else ""


def is_sprint_field(schema_key: str) -> bool:
    """Spec 90 read `customfield_10002` unconditionally — so on an instance where
    that ID is something else, its values were parsed as sprints and silently
    created cycles named after whatever they happened to contain."""
    return schema_key == JiraSchemaKey.SPRINT.value


def is_epic_link_field(schema_key: str) -> bool:
    return schema_key in (JiraSchemaKey.EPIC_LINK.value, JiraSchemaKey.PARENT_LINK.value)


def find_by_schema_key(
    catalog: dict[str, dict], key: JiraSchemaKey | str
) -> list[str]:
    """Every field ID on THIS instance with the given type key.

    A list, not a single ID: a real instance can carry several. The live check on
    2026-07-28 found two `gh-lexo-rank` fields — "Rank" and "Queue Order" — which
    spec 90 could only cover by hardcoding both IDs.
    """
    wanted = key.value if isinstance(key, JiraSchemaKey) else key
    return sorted(
        field_id
        for field_id, meta in (catalog or {}).items()
        if (meta or {}).get("schema_key") == wanted
    )
