"""Every scalar setting is declared by the module that reads it (RADD-891).

`settings/types.py::SettingKey` used to enumerate every feature module's
tunables — `ai_*`, `ldap_*`, `csat_enabled`, `release_*`,
`workflow_transition_mode`, `estimation_points`, the timesheet keys — in one
hardcoded `SETTINGS_REGISTRY` dict, while the kernel `SettingSpec` /
`RaddPlugin.settings_keys` fields that exist for exactly that (mirroring
`PermissionSpec`, spec 93) were read by nothing. Mirrors
`test_permission_ownership.py`'s fix for `auth.types.Permission` one registry
over: the registry is the catalog now, the enum is the typed alias surface
call sites hold, and this file asserts BOTH directions plus the ownership rule
itself: `settings` declares no keys of its own — it is pure cascade mechanism.

Pure/in-memory — reads the registry conftest's autouse fixture loads.
"""

from radd.kernel import registries
from radd.modules.settings.types import SettingKey, SettingScope, SettingType, all_setting_keys


def _declared() -> dict[str, set[str]]:
    """key -> the plugins that declare it, over the loaded registry."""
    out: dict[str, set[str]] = {}
    for plugin in registries.plugins.values():
        for spec in plugin.settings_keys:
            out.setdefault(spec.key, set()).add(plugin.name)
    return out


def test_every_key_has_an_owning_module():
    """enum ⊆ registry. A key added to the alias alone has no type, no scopes,
    no description and no default source — `resolve()`/`list_for_scope` would
    KeyError the moment anything touched it."""
    declared = _declared()
    orphans = sorted(k.value for k in SettingKey if k.value not in declared)
    assert not orphans, (
        "keys in settings.types.SettingKey that no plugin declares — put each on "
        "the settings_keys= of the module that reads it:\n  " + "\n  ".join(orphans)
    )


def test_no_key_has_two_owners():
    """One declaration per key. Two modules claiming `ai_summarize` means two
    descriptions and two default sources, and which one the catalog serves is
    dict-ordering luck."""
    shared = {k: sorted(v) for k, v in _declared().items() if len(v) > 1}
    assert not shared, f"keys declared by more than one plugin: {shared}"


def test_registry_adds_no_key_the_alias_cannot_name():
    """registry ⊆ enum. This is what keeps every `SettingKey.X` call site (and
    the FastAPI/pydantic types built from it) working: a key contributed by a
    module with no enum member would be resolvable and unnameable in Python."""
    assert all_setting_keys() == frozenset(k.value for k in SettingKey)


def test_settings_declares_no_keys_itself():
    """`settings` is pure cascade MECHANISM (resolution order, coercion, the
    /scoped-settings API) — every key belongs to the feature that reads it,
    same as auth declaring no feature's permission atoms (RADD-890)."""
    settings_plugin = registries.plugins["settings"]
    assert settings_plugin.settings_keys == ()


def test_every_key_reads_as_a_sentence():
    """Label and description both resolve for every registered key — this is
    what `GET /scoped-settings` renders in the generic settings editor, so a
    blank one is a blank row with no idea what it does."""
    for plugin in registries.plugins.values():
        for spec in plugin.settings_keys:
            assert spec.label, f"{spec.key}: no label ({plugin.name})"
            assert spec.description and spec.description.endswith("."), (
                f"{spec.key}: {spec.description!r} ({plugin.name})"
            )


def test_every_key_declares_known_type_and_scopes():
    """`SettingSpec.type`/`.scopes` are plain strings (kernel purity forbids
    importing `settings.types`'s enums) — this is what keeps them from
    silently drifting to a value `SettingType`/`SettingScope` doesn't know."""
    known_types = {t.value for t in SettingType}
    known_scopes = {s.value for s in SettingScope}
    for plugin in registries.plugins.values():
        for spec in plugin.settings_keys:
            assert spec.type in known_types, f"{spec.key}: unknown type {spec.type!r}"
            assert spec.scopes, f"{spec.key}: declares no scopes at all"
            assert set(spec.scopes) <= known_scopes, (
                f"{spec.key}: unknown scope(s) {set(spec.scopes) - known_scopes}"
            )


def test_every_key_default_resolves():
    """`SettingSpec.default` is dynamic dispatch onto `config.Settings`
    (`getattr(_config, config_attr or key)`) — the biggest dynamic-dispatch
    trap the registry carries. A key whose `config_attr` (or bare name) has no
    matching `config.Settings` attribute would AttributeError the first time
    anything resolved it; this fails at collection time instead."""
    for plugin in registries.plugins.values():
        for spec in plugin.settings_keys:
            spec.default  # noqa: B018 — the assertion IS "this doesn't raise"
