"""Scalar settings registry (specs 50/67; RADD-891).

A *scalar* setting is a single value that resolves project → instance, falling
back to the env/config default (`config.Settings`). This is distinct from the
*collection* cascade (custom fields, SLA policies, labels…) which is additive —
those are NOT registered here. A setting opts into the scalar cascade by being
registered as a `kernel.SettingSpec` (below via the live registry), not by
being a member of an enum.

RADD-891: `SettingKey` used to be BOTH the catalog and the alias — every
feature's tunables (`AI_*`, `LDAP_*`, `CSAT_ENABLED`, `RELEASE_*`,
`WORKFLOW_TRANSITION_MODE`, `ESTIMATION_POINTS`, the timesheet keys) lived in
one hardcoded `SETTINGS_REGISTRY` dict here, while the kernel `SettingSpec` /
`RaddPlugin.settings_keys` fields that exist for exactly this (mirroring
`PermissionSpec`, spec 93) were read by nothing. Mirroring RADD-890's fix for
`auth.types.Permission`: every module now declares the keys IT reads —
`settings_keys=(SettingSpec…),)` on its own `RaddPlugin` — and this module
keeps the CASCADE MECHANISM (resolution order, coercion, the
`/scoped-settings` API) while reading the kernel registry for each key's type,
scopes, prose and default source.

`SettingKey` SURVIVES as the typed alias surface — unlike `SettingSpec`, which
moved to the kernel outright. The reason is the same import-order argument
RADD-890 made for `Permission`: `SettingKey` is used as a FastAPI query-param
type and a pydantic field type (`router.py`, `schemas.py`), both fixed at
IMPORT time of this module's own plugin package — which the loader visits at
a FIXED position in `config.Settings.modules` (early: right after `auth`),
long before `ai`/`ldap`/`releases`/`timelogging`/`workflow`/`items`/`csat` have
registered their keys. A `SettingKey` built from the live registry at that
point would enumerate only the handful of keys owned by plugins loaded before
`settings` — an enum whose membership depends on `RADD_MODULES` order. So the
key STRINGS are ratcheted here exactly like `Permission`'s atoms, and
`tests/test_setting_ownership.py` asserts both directions (registry ⊆ enum,
enum ⊆ registry) so an addition to one side alone fails the suite.

Unlike `Permission`, nothing here computes eagerly FROM the full key set at
settings' own import time (there is no settings equivalent of auth's
`PROJECT_PERMISSIONS`) — every read (`resolve`/`set_value`/`list_for_scope`)
runs at REQUEST time, well after `load_plugins` has loaded every plugin. So the
per-key POLICY (type, scopes, description, default source) is looked up LIVE
from `radd.kernel.registries.settings` with no static mirror to keep in sync,
unlike `Permission`'s `_PROJECT_SCOPED`/`_SPACE_SCOPED` tables.
"""

from collections.abc import Mapping
from enum import StrEnum

from radd.kernel import SettingSpec

# Re-exported for callers that used to import the dataclass from here — the
# type itself now lives in the kernel (`radd.kernel.SettingSpec`), since a
# plugin declaring `settings_keys=(SettingSpec(...),)` must be able to build
# one without importing this module (settings depends on no feature plugin).
__all__ = [
    "SettingScope",
    "SettingType",
    "SettingKey",
    "SettingSpec",
    "SettingsEntity",
    "SETTINGS_REGISTRY",
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
    """A registered scalar setting — RADD-891's typed alias surface.

    Every atom's TYPE, SCOPES, prose and default source now live on the owning
    module's `kernel.SettingSpec` contribution (`setting_spec(key)` below reads
    it live); this enum is only the string call sites and FastAPI/pydantic
    type-check against. See the module docstring for why it cannot be built
    from the registry instead."""

    WORK_WEEK_DAYS = "work_week_days"
    TIMELOG_HOURS_PER_DAY = "timelog_hours_per_day"
    # Timesheet outlier flags: a workday with less/more logged
    # than these bounds gets highlighted for coordinators.
    TIMESHEET_DAY_MIN_HOURS = "timesheet_day_min_hours"
    TIMESHEET_DAY_MAX_HOURS = "timesheet_day_max_hours"
    WORKFLOW_TRANSITION_MODE = "workflow_transition_mode"
    CSAT_ENABLED = "csat_enabled"
    ESTIMATION_POINTS = "estimation_points"
    ITEM_DEFAULT_VISIBILITY = "item_default_visibility"  # spec 121
    # Spec 122: a collaborative session writes a history row only when the
    # previous one is older than this many seconds (or the save is final).
    PAGE_COLLAB_VERSION_WINDOW_SECONDS = "page_collab_version_window_seconds"
    # The ack's admin-editable body (spec 47/62, RADD-1045) — Settings → Email.
    MAIL_ACK_BODY = "mail_ack_body"
    # RADD-982: mail the ticket's external contacts when it resolves. Per
    # project, because one instance runs both a service desk and a dev project.
    MAIL_SEND_RESOLVED = "mail_send_resolved"
    # RADD-1048: days of RAW inbound bytes kept. Instance-only, and read by both
    # ends of the window — intake asks before storing, the sweep before deleting.
    MAIL_RAW_RETENTION_DAYS = "mail_raw_retention_days"
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
    # AI feature toggles (spec 101) — instance-only, owned by Settings → AI.
    AI_EDITOR_ACTIONS = "ai_editor_actions"
    AI_SEMANTIC_SEARCH = "ai_semantic_search"
    AI_STORAGE_ROUTING = "ai_storage_routing"
    AI_MAIL_ROUTING = "ai_mail_routing"
    AI_SUMMARIZE = "ai_summarize"
    AI_NL_SLQ = "ai_nl_slq"
    AI_SIMILAR_RERANK = "ai_similar_rerank"
    AI_VALIDATION = "ai_validation"  # spec 119 — the ai.validate automation node
    AI_GENERATION = "ai_generation"  # spec 120 — the ai.generate automation node
    AI_STREAM_RESPONSES = "ai_stream_responses"
    # Spec 112 — the release pipeline. Both empty = the pipeline is off for
    # the project, and neither the merge transition nor the sweep does anything.
    RELEASE_WAITING_STATE = "release_waiting_state"
    RELEASE_SHIPPED_STATE = "release_shipped_state"


class SettingsEntity(StrEnum):
    SETTING = "scoped_setting"


class SettingEvent(StrEnum):
    """Spec 123: a scoped setting's value changed — `entity_id` is the KEY,
    the payload names the scope, `changes` carries old → new (clearing an
    override is `to: null`). Before this, `set_value` emitted nothing: who
    made a project's issues public by default, or changed SLA hours, left no
    trace anywhere."""

    CHANGED = "setting.changed"


def all_setting_keys() -> frozenset[str]:
    """Every key the system knows: the registry ∪ the typed alias enum (mirrors
    `auth.types.all_permission_keys`)."""
    from radd.kernel import registries

    return frozenset({k.value for k in SettingKey} | set(registries.settings))


def setting_spec(key: "SettingKey | str") -> SettingSpec:
    """The owning module's declaration for `key` — type, scopes, prose, default
    source — read LIVE from the kernel registry, so a hot-disabled plugin's
    setting stops resolving in the same breath its routes unmount."""
    from radd.kernel import registries

    spec = registries.settings.get(str(key))
    if spec is None:
        raise KeyError(key)
    return spec


class _SettingCatalog(Mapping[str, SettingSpec]):
    """`{key: SettingSpec}` over the LIVE kernel registry (RADD-891) — the
    settings equivalent of `auth.types._DescriptionCatalog`/`PERMISSION_
    DESCRIPTIONS`. Presented as a Mapping (not a function) so existing call
    sites — `SETTINGS_REGISTRY[key]`, `SETTINGS_REGISTRY.items()` — keep
    working unchanged, now composed from each owning plugin's own contribution
    instead of one hardcoded dict literal."""

    def __getitem__(self, key: "SettingKey | str") -> SettingSpec:
        return setting_spec(key)

    def __iter__(self):
        from radd.kernel import registries

        return iter(registries.settings)

    def __len__(self) -> int:
        from radd.kernel import registries

        return len(registries.settings)


#: `{key: SettingSpec}` — every registered scalar setting, live over the
#: kernel registry. Kept as a module-level Mapping (rather than a function)
#: for the same reason `auth.types.PERMISSION_DESCRIPTIONS` is: existing call
#: sites subscript and iterate it like the old static dict.
SETTINGS_REGISTRY: Mapping[str, SettingSpec] = _SettingCatalog()
