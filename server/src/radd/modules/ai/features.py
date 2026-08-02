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
from .types import AiDisabledError, AiFeature, AiRole

# The ai plugin's id in the kernel registry (what `/plugins` toggles).
_PLUGIN_ID = "ai"

FEATURE_ROLE: dict[AiFeature, AiRole] = {
    AiFeature.EDITOR_ACTIONS: AiRole.CHAT,
    AiFeature.SEMANTIC_SEARCH: AiRole.EMBEDDINGS,
    AiFeature.STORAGE_ROUTING: AiRole.VISION,
    AiFeature.SUMMARIZE: AiRole.CHAT,
    AiFeature.NL_SLQ: AiRole.CHAT,
    AiFeature.SIMILAR_RERANK: AiRole.CHAT,
}

FEATURE_SETTING: dict[AiFeature, SettingKey] = {
    AiFeature.EDITOR_ACTIONS: SettingKey.AI_EDITOR_ACTIONS,
    AiFeature.SEMANTIC_SEARCH: SettingKey.AI_SEMANTIC_SEARCH,
    AiFeature.STORAGE_ROUTING: SettingKey.AI_STORAGE_ROUTING,
    AiFeature.SUMMARIZE: SettingKey.AI_SUMMARIZE,
    AiFeature.NL_SLQ: SettingKey.AI_NL_SLQ,
    AiFeature.SIMILAR_RERANK: SettingKey.AI_SIMILAR_RERANK,
}


def plugin_loaded() -> bool:
    """False once the ai PLUGIN is disabled (kernel registry). Routes unmount
    separately; this is the chokepoint for every CROSS-MODULE seam that calls
    in sideways — search fusion/semantic/deflection, storage's llm routing
    rule — which import this module lazily and would otherwise keep working
    off the still-populated role snapshot after a runtime disable."""
    return _PLUGIN_ID in registries.plugins


async def feature_enabled(session: AsyncSession, feature: AiFeature) -> bool:
    if not plugin_loaded():
        return False
    if not await settings_service.resolve(session, FEATURE_SETTING[feature]):
        return False
    return await registry.resolve_role(session, FEATURE_ROLE[feature]) is not None


async def require_feature(session: AsyncSession, feature: AiFeature) -> None:
    if not await feature_enabled(session, feature):
        raise AiDisabledError()
