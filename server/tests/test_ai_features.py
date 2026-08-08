"""The AI feature gate's dispatch tables must be TOTAL over `AiFeature`.

This file exists because of RADD-989. `AiFeature.MAIL_ROUTING` was added to the
enum, wired into `mailintake.routing`, and added to NEITHER dict in
`ai.features` nor the settings registry — so `feature_enabled` raised KeyError
instead of answering, mailintake's per-rule `except Exception` swallowed it as
"rule raised, skipped", and every llm mail rule fell through on every message
for a release. Nothing was red: the enum compiled, the call type-checked, the
tests passed (they only pinned the fall-through side), and the feature simply
never ran.

Three registries have to agree — the enum, the two gate tables, and the scalar
settings catalog — and a member is only as wired as its worst one. Asserting
equality of key SETS is what makes the next feature impossible to half-add.
"""

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config_settings
from radd.modules.ai.features import FEATURE_ROLE, FEATURE_SETTING
from radd.modules.ai.types import AiFeature
from radd.modules.settings.types import SettingKey


@pytest.fixture
async def db():
    engine = create_async_engine(config_settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


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
    """The blast radius, and the part of RADD-989 that was never diagnosed.

    `GET /ai/status` builds its map by iterating `AiFeature` and calling the gate
    for each, so ONE unwired member does not disable one feature — it raises out
    of the endpoint the entire SPA gates every AI affordance on. The mail-routing
    KeyError took editor actions, summarize, semantic search and NL→SLQ down with
    it for any instance running the ai plugin.
    """
    from radd.modules.ai import service as ai_service

    result = await ai_service.status(db)
    assert set(result.features) == {feature.value for feature in AiFeature}
