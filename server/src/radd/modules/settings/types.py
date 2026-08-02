"""Scalar settings registry (specs 50/67).

A *scalar* setting is a single value that resolves project → instance, falling
back to the env/config default (`config.Settings`). This is distinct from the
*collection* cascade (custom fields, SLA policies, labels…) which is additive —
those are NOT registered here. A setting opts into the scalar cascade by being
registered below; only registered keys cascade (dev-rule 2: no magic values).

Spec 67 collapsed the original three-level cascade (project → workspace →
instance) to two: for a single-workspace deployment the workspace layer only
duplicated the instance one.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from radd.config import settings as _config


class SettingScope(StrEnum):
    """The two cascade levels, narrow → wide (spec 67: workspace scope retired)."""

    PROJECT = "project"
    INSTANCE = "instance"


class SettingType(StrEnum):
    STRING = "string"
    INT = "int"
    BOOL = "bool"


class SettingKey(StrEnum):
    """A registered scalar setting. The value matches the `config.Settings`
    attribute that supplies the ultimate instance default (the env fallback),
    unless the spec names a different attribute via `config_attr`."""

    WORK_WEEK_DAYS = "work_week_days"
    TIMELOG_HOURS_PER_DAY = "timelog_hours_per_day"
    # Timesheet outlier flags: a workday with less/more logged
    # than these bounds gets highlighted for coordinators.
    TIMESHEET_DAY_MIN_HOURS = "timesheet_day_min_hours"
    TIMESHEET_DAY_MAX_HOURS = "timesheet_day_max_hours"
    WORKFLOW_TRANSITION_MODE = "workflow_transition_mode"
    CSAT_ENABLED = "csat_enabled"
    ESTIMATION_POINTS = "estimation_points"
    # Directory settings page + automatic user sync (spec 85) — instance-only.
    LDAP_USER_SYNC_BASE = "ldap_user_sync_base"
    LDAP_USER_SYNC_ENABLED = "ldap_user_sync_enabled"
    LDAP_USER_SYNC_DEACTIVATE_MISSING = "ldap_user_sync_deactivate_missing"
    LDAP_GROUP_SEARCH_BASE = "ldap_group_search_base"
    LDAP_EXCLUDE_DISABLED = "ldap_exclude_disabled"
    # AI feature toggles (spec 101) — instance-only, owned by Settings → AI.
    AI_EDITOR_ACTIONS = "ai_editor_actions"
    AI_SEMANTIC_SEARCH = "ai_semantic_search"
    AI_STORAGE_ROUTING = "ai_storage_routing"
    AI_SUMMARIZE = "ai_summarize"
    AI_NL_SLQ = "ai_nl_slq"
    AI_SIMILAR_RERANK = "ai_similar_rerank"
    AI_STREAM_RESPONSES = "ai_stream_responses"
    # Spec 112 — the release pipeline. Both empty = the pipeline is off for
    # the project, and neither the merge transition nor the sweep does anything.
    RELEASE_WAITING_STATE = "release_waiting_state"
    RELEASE_SHIPPED_STATE = "release_shipped_state"


@dataclass(frozen=True)
class SettingSpec:
    key: SettingKey
    type: SettingType
    scopes: tuple[SettingScope, ...]  # scopes at which a value may be SET
    label: str
    description: str
    # The `config.Settings` attribute supplying the env default when it differs
    # from the key name (spec 85: `ldap_user_sync_base` defaults to the
    # pre-existing RADD_LDAP_USER_SEARCH_BASE so deploys keep working).
    config_attr: str | None = None
    # Enumerated STRING settings (spec 107 cleanup): the only accepted values —
    # writes outside the set 409 (a free-typed "gaurds" must never reach a
    # StrEnum coercion at read time) and the generic settings editor renders a
    # select instead of a text input.
    choices: tuple[str, ...] | None = None

    @property
    def default(self) -> Any:
        """The ultimate fallback: the instance's env/config value."""
        return getattr(_config, self.config_attr or self.key.value)


SETTINGS_REGISTRY: dict[SettingKey, SettingSpec] = {
    # --- spec 112: the release pipeline ---------------------------------
    # State NAMES, not ids: a project's states are per-project rows, and a name
    # is what an admin sees in the picker. Resolution is by name within the
    # project, so a renamed state is a settings edit, not a broken pipeline.
    SettingKey.RELEASE_WAITING_STATE: SettingSpec(
        key=SettingKey.RELEASE_WAITING_STATE,
        type=SettingType.STRING,
        scopes=(SettingScope.INSTANCE, SettingScope.PROJECT),
        label="Waiting-for-release state",
        description=(
            "The state a merged pull request moves work to: complete, not yet shipped. "
            "Belongs to the DONE category, so throughput counts the day the work was "
            "finished rather than the day someone cut a tag. Empty turns the pipeline off."
        ),
    ),
    SettingKey.RELEASE_SHIPPED_STATE: SettingSpec(
        key=SettingKey.RELEASE_SHIPPED_STATE,
        type=SettingType.STRING,
        scopes=(SettingScope.INSTANCE, SettingScope.PROJECT),
        label="Shipped state",
        description=(
            "Where the release sweep moves waiting work when a version is published, "
            "with the release recorded on each item. Empty turns the sweep off."
        ),
    ),
    SettingKey.WORK_WEEK_DAYS: SettingSpec(
        key=SettingKey.WORK_WEEK_DAYS,
        type=SettingType.STRING,
        scopes=(SettingScope.INSTANCE, SettingScope.PROJECT),
        label="Working week",
        description=(
            "Comma-separated working days (mon,tue,wed,thu,fri). Business-day SLAs "
            "resolve this per item project; the instance sets the default, projects "
            "override."
        ),
    ),
    SettingKey.TIMELOG_HOURS_PER_DAY: SettingSpec(
        key=SettingKey.TIMELOG_HOURS_PER_DAY,
        type=SettingType.INT,
        scopes=(SettingScope.INSTANCE,),  # global — no per-project override (spec 67 follow-up)
        label="Hours per working day",
        description=(
            "How many hours a '1d' duration means when logging time or setting estimates. "
            "Global — one instance-wide value, so durations mean the same thing on every "
            "timesheet and cycle handle."
        ),
    ),
    SettingKey.TIMESHEET_DAY_MIN_HOURS: SettingSpec(
        key=SettingKey.TIMESHEET_DAY_MIN_HOURS,
        type=SettingType.INT,
        scopes=(SettingScope.INSTANCE,),
        label="Timesheet: minimum hours per workday",
        description=(
            "A working day (per the working week) with less than this logged is "
            "flagged as under-logged on the timesheet's per-person view. Leave and "
            "holiday days are never flagged."
        ),
    ),
    SettingKey.TIMESHEET_DAY_MAX_HOURS: SettingSpec(
        key=SettingKey.TIMESHEET_DAY_MAX_HOURS,
        type=SettingType.INT,
        scopes=(SettingScope.INSTANCE,),
        label="Timesheet: maximum hours per day",
        description=(
            "Any day with more than this logged is flagged as over-logged on the "
            "timesheet's per-person view."
        ),
    ),
    SettingKey.WORKFLOW_TRANSITION_MODE: SettingSpec(
        key=SettingKey.WORKFLOW_TRANSITION_MODE,
        type=SettingType.STRING,
        scopes=(SettingScope.INSTANCE, SettingScope.PROJECT),
        # Mirror of workflow.types.TransitionMode (settings must not import a
        # module that depends on it).
        choices=("off", "guards", "strict"),
        label="Workflow transition enforcement",
        description=(
            "Off: anyone can move items to any state — the transitions list is "
            "ignored. Guarded: a move that has a transition defined must meet its "
            "conditions and approvals; moves with no transition defined stay "
            "allowed. Strict: the list becomes the complete map — a move with no "
            "transition defined is blocked outright (and defined moves still check "
            "their conditions). Set per project, or here for every project."
        ),
    ),
    SettingKey.CSAT_ENABLED: SettingSpec(
        key=SettingKey.CSAT_ENABLED,
        type=SettingType.BOOL,
        scopes=(SettingScope.INSTANCE, SettingScope.PROJECT),
        label="CSAT surveys",
        description=(
            "Email the requester a one-click satisfaction survey when their item "
            "resolves (spec 65). Off by default — enable per service-desk project; "
            "dev projects never send surveys."
        ),
    ),
    SettingKey.ESTIMATION_POINTS: SettingSpec(
        key=SettingKey.ESTIMATION_POINTS,
        type=SettingType.BOOL,
        scopes=(SettingScope.INSTANCE, SettingScope.PROJECT),
        label="Story points",
        description=(
            "Estimate items in story points (0–999, one decimal) alongside time "
            "tracking (spec 70). Off by default — a project that hasn't opted in "
            "shows no points UI; velocity/burnup can then report in points."
        ),
    ),
    # Directory (spec 85) — instance-only, edited on Settings → Directory. An
    # empty base DN means "the whole directory": consumers fall back to
    # ldap.service.base_dn() at USE time (mirroring the raw-env helpers), so the
    # registered default stays the verbatim env value.
    SettingKey.LDAP_USER_SYNC_BASE: SettingSpec(
        key=SettingKey.LDAP_USER_SYNC_BASE,
        type=SettingType.STRING,
        scopes=(SettingScope.INSTANCE,),
        label="User search base DN",
        description=(
            "Where directory users are searched (user sync, imports, group-member "
            "resolution) — e.g. OU=Staff,DC=ad,DC=example,DC=com. Empty = the "
            "whole directory."
        ),
        config_attr="ldap_user_search_base",
    ),
    SettingKey.LDAP_USER_SYNC_ENABLED: SettingSpec(
        key=SettingKey.LDAP_USER_SYNC_ENABLED,
        type=SettingType.BOOL,
        scopes=(SettingScope.INSTANCE,),
        label="Automatic user sync",
        description=(
            "Periodically import every directory user under the search base and "
            "keep names in sync (spec 85). Needs the bind account and background "
            "workers; off = manual imports and 'Sync now' only."
        ),
    ),
    SettingKey.LDAP_USER_SYNC_DEACTIVATE_MISSING: SettingSpec(
        key=SettingKey.LDAP_USER_SYNC_DEACTIVATE_MISSING,
        type=SettingType.BOOL,
        scopes=(SettingScope.INSTANCE,),
        label="Deactivate missing users",
        description=(
            "When a directory-provisioned user vanishes from the directory, "
            "deactivate the account (revokes sessions). Local and OIDC accounts "
            "are never touched. Off by default so a transient AD outage cannot "
            "lock people out."
        ),
    ),
    SettingKey.LDAP_EXCLUDE_DISABLED: SettingSpec(
        key=SettingKey.LDAP_EXCLUDE_DISABLED,
        type=SettingType.BOOL,
        scopes=(SettingScope.INSTANCE,),
        label="Skip disabled directory accounts",
        description=(
            "Exclude accounts disabled in the directory (the AD ACCOUNTDISABLE bit) "
            "from imports and sync. ON by default: on a real directory most entries "
            "are leavers — one live instance had 2057 disabled accounts against 1031 "
            "active ones — and importing them fills Radd with dead users. Turning it "
            "OFF does NOT lose the history of people who have left: their existing "
            "issues, comments and worklogs keep their attribution either way."
        ),
    ),
    SettingKey.LDAP_GROUP_SEARCH_BASE: SettingSpec(
        key=SettingKey.LDAP_GROUP_SEARCH_BASE,
        type=SettingType.STRING,
        scopes=(SettingScope.INSTANCE,),
        label="Group search base DN",
        description=(
            "Where directory groups are searched for the group browser, links, "
            "and imports — e.g. OU=Groups,DC=ad,DC=example,DC=com. Empty = the "
            "whole directory."
        ),
    ),
    SettingKey.AI_EDITOR_ACTIONS: SettingSpec(
        key=SettingKey.AI_EDITOR_ACTIONS,
        type=SettingType.BOOL,
        scopes=(SettingScope.INSTANCE,),
        label="Editor AI actions",
        description=(
            "AI writing actions in the rich editor (/refine, /format, preset and "
            "freeform prompts) with streamed results and diff review. Also needs "
            "the chat role assigned; users can additionally opt out per profile."
        ),
    ),
    SettingKey.AI_SEMANTIC_SEARCH: SettingSpec(
        key=SettingKey.AI_SEMANTIC_SEARCH,
        type=SettingType.BOOL,
        scopes=(SettingScope.INSTANCE,),
        label="Semantic search",
        description=(
            "Meaning-based retrieval fused into search, similar-issues, and the "
            "palette Ask mode. Needs the embeddings role assigned and the pgvector "
            "extension installed in Postgres."
        ),
    ),
    SettingKey.AI_STORAGE_ROUTING: SettingSpec(
        key=SettingKey.AI_STORAGE_ROUTING,
        type=SettingType.BOOL,
        scopes=(SettingScope.INSTANCE,),
        label="LLM storage routing",
        description=(
            "Lets LLM-type storage routing rules classify uploads (Settings → "
            "Storage). Needs the vision role assigned; rules fall through to the "
            "next rule while this is off."
        ),
    ),
    SettingKey.AI_SUMMARIZE: SettingSpec(
        key=SettingKey.AI_SUMMARIZE,
        type=SettingType.BOOL,
        scopes=(SettingScope.INSTANCE,),
        label="Issue summarize",
        description="The Summarize action on issues (chat role).",
    ),
    SettingKey.AI_NL_SLQ: SettingSpec(
        key=SettingKey.AI_NL_SLQ,
        type=SettingType.BOOL,
        scopes=(SettingScope.INSTANCE,),
        label="Natural language → SLQ",
        description="The Ask-AI bar that turns plain language into an SLQ filter (chat role).",
    ),
    SettingKey.AI_SIMILAR_RERANK: SettingSpec(
        key=SettingKey.AI_SIMILAR_RERANK,
        type=SettingType.BOOL,
        scopes=(SettingScope.INSTANCE,),
        label="Similar-issues LLM rerank",
        description=(
            "Rescore duplicate candidates with the chat model and explain why "
            "each looks related. Off by default — it costs a chat-model round "
            "trip per similar-issues open; similar issues keep working without "
            "it (FTS/vector candidates only)."
        ),
    ),
    SettingKey.AI_STREAM_RESPONSES: SettingSpec(
        key=SettingKey.AI_STREAM_RESPONSES,
        type=SettingType.BOOL,
        scopes=(SettingScope.INSTANCE,),
        label="Stream AI responses",
        description=(
            "Deliver issue summaries progressively and similar-issue candidates "
            "immediately with reasoning filled in as the model produces it. Off = "
            "each AI answer arrives complete, in one go."
        ),
    ),
}


class SettingsEntity(StrEnum):
    SETTING = "scoped_setting"
