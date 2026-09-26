"""Scalar settings: one value resolving project → instance → the env/config default.

Each owning plugin declares its keys as `kernel.SettingSpec`s (RADD-891); this module keeps
the cascade vocabulary. `SettingKey` survives as the typed alias FastAPI and pydantic check
against: it is fixed at `settings`' early import, before most owners register, so a
registry-built enum would depend on RADD_MODULES order. tests/test_setting_ownership.py keeps
enum and registry equal."""

from enum import StrEnum

from radd.kernel import SettingSpec, registries

__all__ = [
    "SettingScope",
    "SettingType",
    "SettingKey",
    "SettingsEntity",
    "all_setting_keys",
    "setting_spec",
]


class SettingScope(StrEnum):
    """The two cascade levels, narrow → wide (spec 67: workspace scope retired)."""

    PROJECT = "project"
    INSTANCE = "instance"


class SettingType(StrEnum):
    STRING = "string"
    INT = "int"
    BOOL = "bool"


class SettingKey(StrEnum):
    """Registered scalar setting keys (RADD-891); each key's policy is its owner's SettingSpec."""

    WORK_WEEK_DAYS = "work_week_days"
    TIMELOG_HOURS_PER_DAY = "timelog_hours_per_day"
    # Timesheet outlier flags: a workday logged outside these bounds is highlighted.
    TIMESHEET_DAY_MIN_HOURS = "timesheet_day_min_hours"
    TIMESHEET_DAY_MAX_HOURS = "timesheet_day_max_hours"
    WORKFLOW_TRANSITION_MODE = "workflow_transition_mode"
    CSAT_ENABLED = "csat_enabled"
    ESTIMATION_POINTS = "estimation_points"
    ITEM_DEFAULT_VISIBILITY = "item_default_visibility"  # spec 121
    # Spec 122: a collaborative session writes a history row only when the
    # previous one is older than this many seconds (or the save is final).
    PAGE_COLLAB_VERSION_WINDOW_SECONDS = "page_collab_version_window_seconds"
    # RADD-1368: what the desk mails a requester unprompted; per project, OFF by default.
    MAIL_SEND_ACK = "mail_send_ack"
    MAIL_ACK_BODY = "mail_ack_body"
    MAIL_SEND_RESOLVED = "mail_send_resolved"
    # Directory settings page + automatic user sync (spec 85) — instance-only.
    LDAP_URL = "ldap_url"
    LDAP_USER_DOMAIN = "ldap_user_domain"
    LDAP_BIND_DN = "ldap_bind_dn"
    LDAP_BIND_PASSWORD = "ldap_bind_password"
    LDAP_ADMIN_GROUPS = "ldap_admin_groups"
    LDAP_GROUP_SYNC_SECONDS = "ldap_group_sync_seconds"  # RADD-848
    LDAP_USER_SYNC_BASE = "ldap_user_sync_base"
    LDAP_USER_SYNC_ENABLED = "ldap_user_sync_enabled"
    LDAP_USER_SYNC_DEACTIVATE_MISSING = "ldap_user_sync_deactivate_missing"
    LDAP_GROUP_SEARCH_BASE = "ldap_group_search_base"
    LDAP_EXCLUDE_DISABLED = "ldap_exclude_disabled"
    # RADD-1279 — instance-only, owned by auth, rendered on Settings → Sign-in.
    REQUIRE_MFA = "require_mfa"
    # AI feature toggles (spec 101) — instance-only, owned by Settings → AI.
    AI_EDITOR_ACTIONS = "ai_editor_actions"
    AI_SEMANTIC_SEARCH = "ai_semantic_search"
    AI_STORAGE_ROUTING = "ai_storage_routing"
    AI_MAIL_SIGNATURE = "ai_mail_signature"
    AI_MAIL_ROUTING = "ai_mail_routing"
    AI_SUMMARIZE = "ai_summarize"
    AI_NL_SLQ = "ai_nl_slq"
    AI_SIMILAR_RERANK = "ai_similar_rerank"
    AI_VALIDATION = "ai_validation"  # spec 119 — the ai.validate automation node
    AI_GENERATION = "ai_generation"  # spec 120 — the ai.generate automation node
    AI_STREAM_RESPONSES = "ai_stream_responses"


class SettingsEntity(StrEnum):
    SETTING = "scoped_setting"


class SettingEvent(StrEnum):
    """Spec 123: a value changed — `entity_id` is the KEY, the payload names the scope,
    `changes` carries old → new (clearing an override is `to: null`)."""

    CHANGED = "setting.changed"


def all_setting_keys() -> frozenset[str]:
    """Every key the system knows: the registry ∪ the typed alias enum."""
    return frozenset({k.value for k in SettingKey} | set(registries.settings))


def setting_spec(key: "SettingKey | str") -> SettingSpec:
    """The owning module's declaration for `key` — type, scopes, prose, default
    source — read LIVE from the kernel registry, so a hot-disabled plugin's
    setting stops resolving in the same breath its routes unmount."""
    spec = registries.settings.get(str(key))
    if spec is None:
        raise KeyError(key)
    return spec

