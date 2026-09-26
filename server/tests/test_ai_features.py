"""The AI feature gate's dispatch tables must be TOTAL over `AiFeature`.

RADD-989: `MAIL_ROUTING` joined the enum but neither gate table, so
`feature_enabled` raised KeyError, mailintake swallowed it as "rule raised,
skipped", and every llm mail rule fell through for a release with nothing red.
The enum, the two gate tables and the settings catalog must have equal key SETS.
"""


from radd.config import settings as config_settings
from radd.modules.ai.features import FEATURE_ROLE, FEATURE_SETTING
from radd.modules.ai.types import AiFeature
from radd.modules.settings.types import SettingKey


def test_every_feature_declares_a_role():
    assert set(FEATURE_ROLE) == set(AiFeature), (
        "every AiFeature needs a role in FEATURE_ROLE — a missing one is a "
        "KeyError at the gate, not a disabled feature"
    )


def test_every_feature_declares_a_setting():
    assert set(FEATURE_SETTING) == set(AiFeature), (
        "every AiFeature needs a SettingKey in FEATURE_SETTING — a missing one "
        "is a KeyError at the gate, not a disabled feature"
    )


def test_every_feature_setting_is_a_registered_key_with_an_env_default():
    """The gate reads `settings_service.resolve(key)`, which looks the key up in
    the kernel registry and falls back to `config.Settings`. A key that is only
    an enum member resolves to nothing; one with no config field has no default
    for a fresh instance. Both are the same silent failure one layer down."""
    for feature, key in FEATURE_SETTING.items():
        assert isinstance(key, SettingKey), feature
        assert hasattr(config_settings, key.value), (
            f"{key.value} has no `config.Settings` field — the env default the "
            f"cascade falls back to for {feature.value}"
        )


def test_the_ai_plugin_registers_a_spec_for_every_feature_setting():
    """`ai/__init__.py`'s `settings_keys` is what puts a toggle on Settings → AI
    and what `settings_service.resolve` reads the type/scope from. The plugin is
    imported directly rather than through the live registry so this holds with or
    without the app booted."""
    from radd.modules.ai import plugin as ai_plugin

    declared = {spec.key for spec in ai_plugin.settings_keys}
    missing = {key.value for key in FEATURE_SETTING.values()} - declared
    assert not missing, f"AI feature settings with no SettingSpec: {sorted(missing)}"


async def test_ai_status_answers_for_every_feature(db):
    """`GET /ai/status` calls the gate for every `AiFeature`, so ONE unwired member
    raises out of the endpoint the SPA gates every AI affordance on — not just its
    own feature."""
    from radd.modules.ai import features

    result = await features.status(db)
    assert set(result.features) == {feature.value for feature in AiFeature}
