"""Jira's stable field-type keys (`schema.custom`, e.g. `…greenhopper.jira:gh-sprint`).

Unlike a field id, a type key is identical on every Jira instance, so Sprint,
Epic Link, board rank and friends are found by key, never by literal id. A match
is a suggestion shown in the mapping step with its reason, always overridable.
"""

from __future__ import annotations

from enum import StrEnum

from .types import BuiltinTarget


class JiraSchemaKey(StrEnum):
    """`schema.custom` values worth recognising. Instance-independent by design."""

    # Jira Software (Greenhopper) — agile.
    SPRINT = "com.pyxis.greenhopper.jira:gh-sprint"
    EPIC_LINK = "com.pyxis.greenhopper.jira:gh-epic-link"
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

# Type keys that are pure machinery (board ordering, the dev-panel blob, colour
# swatches), with the reason the mapping step shows verbatim. Collapsed by
# default — visible and overridable.
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


def find_by_schema_key(
    catalog: dict[str, dict], key: JiraSchemaKey | str
) -> list[str]:
    """Every field id with this type key — a list, because an instance can carry
    several (two `gh-lexo-rank` fields is common)."""
    wanted = key.value if isinstance(key, JiraSchemaKey) else key
    return sorted(
        field_id
        for field_id, meta in (catalog or {}).items()
        if (meta or {}).get("schema_key") == wanted
    )


def sprint_field_ids(catalog: dict[str, dict]) -> tuple[str, ...]:
    return tuple(find_by_schema_key(catalog, JiraSchemaKey.SPRINT))


def epic_link_field_id(catalog: dict[str, dict]) -> str:
    """The Epic Link field: by type key, else by its English name (an instance
    whose catalog carries no `gh-epic-link` key)."""
    found = find_by_schema_key(catalog, JiraSchemaKey.EPIC_LINK)
    if found:
        return found[0]
    return next(
        (fid for fid, meta in (catalog or {}).items() if (meta.get("name") or "").lower() == "epic link"),
        "",
    )
