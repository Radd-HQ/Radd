from fastapi import Request
from fastapi.responses import JSONResponse

from radd.kernel import EntityLinkSpec
from radd.kernel import CapabilitySpec, EventTypeSpec, IntegrationSpec
from radd.kernel import NavItemSpec, PluginUiManifest, RaddPlugin
from radd.kernel import SettingSpec
from radd.kernel.sockets import Socket

from . import registry, storage_rule
from .admin_router import router as admin_router
from .editor_router import router as editor_router
from .embeddings.candidates import SemanticCandidates
from .router import router
from .types import (
    AiConfigError,
    AiDisabledError,
    AiEvent,
    AiInvalidQueryError,
    AiRole,
    AiUpstreamError,
    StorageRuleType,
)


def _toggle(key: str, label: str, description: str) -> SettingSpec:
    """An instance-wide on/off switch on Settings → AI."""
    return SettingSpec(
        key=key, section="ai", page_scopes=("instance",), type="bool", scopes=("instance",),
        label=label, description=description,
    )


def _admin_event(event_type: AiEvent, label: str, entity_type: str, *, diff: bool = False):
    """Spec 123: registry administration is audited, never a trigger."""
    return EventTypeSpec(
        event_type, label, "Admin", has_changes=diff, trigger=False, entity_type=entity_type
    )


async def _startup() -> None:
    await registry.encrypt_plaintext_secrets()  # RADD-1446
    await registry.seed_from_env()
    # Embeddings schema is runtime-managed (see embeddings/__init__): created
    # here when the pgvector extension exists, silently absent otherwise.
    from radd.db import SessionLocal

    from .embeddings import dispatcher as embeddings_dispatcher
    from .embeddings import service as embeddings_service

    async with SessionLocal() as session:
        if await embeddings_service.ensure_schema(session):
            await session.commit()
    await embeddings_dispatcher.start()


async def _shutdown() -> None:
    from .embeddings import dispatcher as embeddings_dispatcher

    await embeddings_dispatcher.stop()


def _chat_capability() -> dict[str, object]:
    """Sync capability check off the process-local role snapshot (refreshed at
    startup and after admin writes) — CapabilitySpec.check cannot await."""
    chat = registry.role_snapshot().get(AiRole.CHAT.value)
    provider = (chat or {}).get("provider", "")
    return {
        "enabled": chat is not None,
        "provider": provider,
        "model": (chat or {}).get("model", ""),
        "summary": provider,  # the one line Server status shows (RADD-1389)
    }


async def _disabled_handler(request: Request, exc: AiDisabledError) -> JSONResponse:
    # Spec 46: a clean 404-style error while no provider is configured.
    return JSONResponse(status_code=404, content={"detail": str(exc)})


async def _config_handler(request: Request, exc: AiConfigError) -> JSONResponse:
    # Spec 101: an invalid registry configuration (e.g. embeddings on anthropic).
    return JSONResponse(status_code=422, content={"detail": str(exc)})


async def _upstream_handler(request: Request, exc: AiUpstreamError) -> JSONResponse:
    # Provider/network failures surface as a clean 502, never a stack trace.
    return JSONResponse(status_code=502, content={"detail": str(exc)})


async def _invalid_query_handler(request: Request, exc: AiInvalidQueryError) -> JSONResponse:
    # NL->SLQ exhausted its retry: hand back the bad query + compile error.
    return JSONResponse(
        status_code=422,
        content={"detail": str(exc), "slq": exc.slq, "error": exc.error},
    )


from . import automation_node as ai_automation_node  # noqa: E402
from . import automation_node_validate as ai_automation_node_validate  # noqa: E402
from . import automation_node_generate as ai_automation_node_generate  # noqa: E402

plugin = RaddPlugin(
    # Every AI surface (Settings → AI, node inspectors, editor/read-mode actions,
    # the palette's Ask, the query bar's NL mode) is this remote's.
    ui=PluginUiManifest(
        remote="/plugins/ai/remoteEntry.js", ui_api_version="2.0.0",
        nav=(NavItemSpec(key="ai", label="AI", path="/settings/ai", section="settings",
                         group="Server", icon="sparkles", order=25, requires_admin=True),),
    ),
    name="ai",
    entity_links=(
        EntityLinkSpec('ai_provider', ('/settings/ai',)),
        EntityLinkSpec('ai_role', ('/settings/ai',)),
        EntityLinkSpec('ai_preset', ('/settings/ai',)),
    ),
    consumer_names=("ai.embedder",),
    consumer_descriptions=(("ai.embedder", "Builds semantic-search vectors"),),
    core=False,  # optional plugin — disableable via the plugin manager
    description=(
        "AI features: summaries, similar-issue suggestions, natural-language search and editor actions, using the providers you configure."
    ),
    event_types=(
        _admin_event(AiEvent.PROVIDER_CREATED, "AI provider created", "ai_provider"),
        _admin_event(AiEvent.PROVIDER_UPDATED, "AI provider updated", "ai_provider", diff=True),
        _admin_event(AiEvent.PROVIDER_DELETED, "AI provider deleted", "ai_provider"),
        _admin_event(AiEvent.ROLE_CHANGED, "AI model role changed", "ai_role", diff=True),
        _admin_event(AiEvent.PRESET_CREATED, "AI preset created", "ai_preset"),
        _admin_event(AiEvent.PRESET_UPDATED, "AI preset updated", "ai_preset", diff=True),
        _admin_event(AiEvent.PRESET_DELETED, "AI preset deleted", "ai_preset"),
    ),
    depends_on=(
        "auth",
        "projects",
        "items",
        "fields",
        "workflow",  # RADD-1140: StateCategory for the NL state-word rewrite
        "comments",
        "search",
        "settings",
        "events",
        "pages",
        "timelogging",
        "attachments",  # RADD-1275: a summary may show a vision model the entity's pictures
    ),
    # Contributed automation nodes (specs 116/119/120): the node registry runs them
    # without `automations` importing `ai`, and disabling this plugin removes them.
    automation_nodes=(
        ai_automation_node.SPEC,
        ai_automation_node_validate.SPEC,
        ai_automation_node_generate.SPEC,
    ),
    # Every AiFeature needs a row here and in features.py; test_ai_features.py enforces it.
    settings_keys=(
        _toggle("ai_mail_signature", "AI email signature detection", "Identify trailing signatures when domain rules and built-in detection do not match. Uses the configured chat provider; email text is sent to that provider."),
        _toggle(
            "ai_editor_actions",
            "Editor AI actions",
            "AI writing actions in the rich editor (/refine, /format, preset and "
            "freeform prompts) with streamed results and diff review. Also needs "
            "the chat role assigned; users can additionally opt out per profile.",
        ),
        _toggle(
            "ai_semantic_search",
            "Semantic search",
            "Meaning-based retrieval fused into search, similar-issues, and the "
            "palette Ask mode. Needs the embeddings role assigned and the pgvector "
            "extension installed in Postgres.",
        ),
        _toggle(
            "ai_storage_routing",
            "LLM storage routing",
            "Lets LLM-type storage routing rules classify uploads (Settings → "
            "Storage). Needs the vision role assigned; rules fall through to the "
            "next rule while this is off.",
        ),
        _toggle(
            "ai_mail_routing",
            "LLM mail routing",
            "Lets AI-type mail routing rules pick the project a new message "
            "opens in from its content (Settings → Email). Needs the chat role "
            "assigned; rules fall through to the next rule while this is off.",
        ),
        _toggle("ai_summarize", "Issue summarize", "The Summarize action on issues (chat role)."),
        _toggle(
            "ai_nl_slq",
            "Natural language → SLQ",
            "The Ask-AI bar that turns plain language into an SLQ filter (chat role).",
        ),
        _toggle(
            "ai_similar_rerank",
            "Similar-issues LLM rerank",
            "Rescore duplicate candidates with the chat model and explain why "
            "each looks related. Off by default — it costs a chat-model round "
            "trip per similar-issues open; similar issues keep working without "
            "it (FTS/vector candidates only).",
        ),
        _toggle(
            "ai_validation",
            "AI intake checks",
            "Lets the AI check step in an automation review a submission against your quality bar and say what falls short. Needs a chat model under Settings → AI. It does nothing until an automation uses it, so this switch is for turning it off everywhere at once.",
        ),
        _toggle(
            "ai_generation",
            "AI value generation",
            "Lets the Generate with AI step in an automation work out values about an issue — a priority, a team, a sentence of advice — for later steps to use. Needs a chat model under Settings → AI. It does nothing until an automation uses it, so this switch is for turning it off everywhere at once.",
        ),
        _toggle(
            "ai_stream_responses",
            "Stream AI responses",
            "Deliver issue summaries progressively and similar-issue candidates "
            "immediately with reasoning filled in as the model produces it. Off = "
            "each AI answer arrives complete, in one go.",
        ),
    ),
    routers=(router, admin_router, editor_router),
    exception_handlers=(
        (AiDisabledError, _disabled_handler),
        (AiConfigError, _config_handler),
        (AiUpstreamError, _upstream_handler),
        (AiInvalidQueryError, _invalid_query_handler),
    ),
    on_startup=(_startup,),
    on_shutdown=(_shutdown,),
    capabilities=(CapabilitySpec("ai", "AI features", "ai", check=_chat_capability),),
    # Sockets, so `search`/`attachments` never import `ai`; disabled, search is
    # FTS-only and the `llm` storage rule type is withdrawn.
    integrations=(
        IntegrationSpec(Socket.SEMANTIC_CANDIDATES, "ai_embeddings", impl=SemanticCandidates()),
        IntegrationSpec(
            Socket.STORAGE_ROUTING_RULE, StorageRuleType.LLM.value, impl=storage_rule.LlmRule()
        ),
    ),
)
