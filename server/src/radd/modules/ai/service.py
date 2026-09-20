"""AI feature flows (spec 46): summarize, similar (semantic-first with an FTS
fallback + optional LLM rerank), and NL->SLQ with server-side compile
validation + one retry.

Every path enforces the caller's ordinary RBAC (item.read via the items/search
services). Nothing is stored — responses go straight back to the caller. The
JSON extractors, rerank merge, and retry decision are pure and unit-tested.

RADD-902: `status` (the one function with no feature-specific section) is the
only code left here — summarize/similar/NL->SLQ were three marker-separated
features sharing almost nothing, so each moved to its own module
(`summarize.py`, `similar.py`, `nlslq.py`) and is re-exported here under its
original name. `router.py`'s `from . import service` + `service.summarize_item(...)`
(etc.) is unaffected; so is `tests/test_ai.py`'s `from radd.modules.ai import
service` for the pure helpers — the one exception is the two `_semantic_pool`/
`search_service` monkeypatches, which now target `similar` directly (see that
module's docstring for why a patch on the facade's re-exported attribute
wouldn't reach the real call site).
"""

from sqlalchemy.ext.asyncio import AsyncSession

from radd.modules.settings import service as settings_service
from radd.modules.settings.types import SettingKey

from . import features, registry
from .nlslq import (
    _NO_QUERY_ERROR as _NO_QUERY_ERROR,
    _compile_error as _compile_error,
    decide as decide,
    extract_json_object as extract_json_object,
    nl_to_slq as nl_to_slq,
)
from .similar import (
    SEMANTIC_MATCH_REASON as SEMANTIC_MATCH_REASON,
    _semantic_pool as _semantic_pool,
    apply_rerank as apply_rerank,
    clean_reason_entry as clean_reason_entry,
    done_only_frames as done_only_frames,
    extract_json_array as extract_json_array,
    fts_candidates as fts_candidates,
    parse_stream_objects as parse_stream_objects,
    search_service as search_service,
    similar_items as similar_items,
    similar_reason_frames as similar_reason_frames,
    similar_reasons_prompt as similar_reasons_prompt,
    similar_to_seed as similar_to_seed,
)
from .summarize import (
    _chat_stream_frames as _chat_stream_frames,
    _worklog_digest as _worklog_digest,
    history_line as history_line,
    summarize_images as summarize_images,
    summarize_item as summarize_item,
    summarize_prompt as summarize_prompt,
    summarize_stream_frames as summarize_stream_frames,
    take_recent as take_recent,
)
from .types import AiFeature, AiRole, AiStatus


async def status(session: AsyncSession) -> AiStatus:
    """{enabled, features, stream_responses} — what the frontend gates on.

    `enabled` = the chat role resolves at all; `features` adds the per-feature
    toggles. Provider/model details are /ai/providers and /ai/roles territory.
    """
    chat = await registry.resolve_role(session, AiRole.CHAT)
    feature_map = {
        feature.value: await features.feature_enabled(session, feature)
        for feature in AiFeature
    }
    stream_on = bool(await settings_service.resolve(session, SettingKey.AI_STREAM_RESPONSES))
    return AiStatus(enabled=chat is not None, features=feature_map, stream_responses=stream_on)
