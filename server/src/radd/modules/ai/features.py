"""Per-feature gates (spec 101): the instance toggle AND the role, together.

A feature is live when its Settings → AI toggle resolves true and its role
(chat | embeddings | vision) resolves to a callable provider. Dormant features
404 (`AiDisabledError`) so they look absent, the spec-46 convention.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from radd.kernel import registries
from radd.modules.settings import service as settings_service
from radd.modules.settings.types import SettingKey

from . import registry
from .types import AiDisabledError, AiFeature, AiRole, AiStatus

# The ai plugin's id in the kernel registry (what `/plugins` toggles).
_PLUGIN_ID = "ai"

# Both tables are TOTAL over AiFeature (tests/test_ai_features.py, RADD-989).
FEATURE_ROLE: dict[AiFeature, AiRole] = {
    AiFeature.EDITOR_ACTIONS: AiRole.CHAT,
    AiFeature.SEMANTIC_SEARCH: AiRole.EMBEDDINGS,
    AiFeature.STORAGE_ROUTING: AiRole.VISION,
    AiFeature.MAIL_SIGNATURE: AiRole.CHAT,
    AiFeature.MAIL_ROUTING: AiRole.CHAT,  # text classification, not an image
    AiFeature.SUMMARIZE: AiRole.CHAT,
    AiFeature.NL_SLQ: AiRole.CHAT,
    AiFeature.SIMILAR_RERANK: AiRole.CHAT,
    AiFeature.VALIDATION: AiRole.CHAT,  # reads a draft and writes prose about it
    AiFeature.GENERATION: AiRole.CHAT,  # fills in named values about an item
}

FEATURE_SETTING: dict[AiFeature, SettingKey] = {
    AiFeature.EDITOR_ACTIONS: SettingKey.AI_EDITOR_ACTIONS,
    AiFeature.SEMANTIC_SEARCH: SettingKey.AI_SEMANTIC_SEARCH,
    AiFeature.STORAGE_ROUTING: SettingKey.AI_STORAGE_ROUTING,
    AiFeature.MAIL_SIGNATURE: SettingKey.AI_MAIL_SIGNATURE,
    AiFeature.MAIL_ROUTING: SettingKey.AI_MAIL_ROUTING,
    AiFeature.SUMMARIZE: SettingKey.AI_SUMMARIZE,
    AiFeature.NL_SLQ: SettingKey.AI_NL_SLQ,
    AiFeature.SIMILAR_RERANK: SettingKey.AI_SIMILAR_RERANK,
    AiFeature.VALIDATION: SettingKey.AI_VALIDATION,
    AiFeature.GENERATION: SettingKey.AI_GENERATION,
}


def plugin_loaded() -> bool:
    """False once the ai plugin is disabled. The gate for callers that reach in
    sideways (mailintake's llm routing rule and signature detection), which would
    otherwise run off the still-populated role snapshot."""
    return _PLUGIN_ID in registries.plugins


async def feature_enabled(session: AsyncSession, feature: AiFeature) -> bool:
    """Toggle on AND role callable. An unregistered feature RAISES rather than
    answering False, so a wiring mistake is loud (RADD-989)."""
    if not plugin_loaded():
        return False
    if not await settings_service.resolve(session, FEATURE_SETTING[feature]):
        return False
    return await registry.resolve_role(session, FEATURE_ROLE[feature]) is not None


async def require_feature(session: AsyncSession, feature: AiFeature) -> None:
    if not await feature_enabled(session, feature):
        raise AiDisabledError()


async def status(session: AsyncSession) -> AiStatus:
    """{enabled, features, stream_responses} — what the frontend gates on.
    `enabled` = the chat role resolves at all; `features` adds the per-feature
    toggles."""
    chat = await registry.resolve_role(session, AiRole.CHAT)
    feature_map = {
        feature.value: await feature_enabled(session, feature) for feature in AiFeature
    }
    stream_on = bool(await settings_service.resolve(session, SettingKey.AI_STREAM_RESPONSES))
    return AiStatus(enabled=chat is not None, features=feature_map, stream_responses=stream_on)
