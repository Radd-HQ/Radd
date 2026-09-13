from fastapi import Request
from fastapi.responses import JSONResponse

from radd.kernel import CapabilitySpec
from radd.kernel import RaddPlugin
from radd.kernel import SettingSpec

from . import registry
from .admin_router import router as admin_router
from .editor_router import router as editor_router
from .router import router
from .types import (
    AiConfigError,
    AiDisabledError,
    AiInvalidQueryError,
    AiRole,
    AiUpstreamError,
)


async def _startup() -> None:
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
    return {
        "enabled": chat is not None,
        "provider": (chat or {}).get("provider", ""),
        "model": (chat or {}).get("model", ""),
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
    name="ai",
    consumer_names=("ai.embedder",),
    core=False,  # optional plugin — disableable via the plugin manager
    description=(
        "Optional provider-agnostic AI: item summarize, similar-item duplicate "
        "candidates (FTS-first, LLM rerank), NL->SLQ (spec 46), plus the provider "
        "registry (spec 101): DB provider rows + chat/embeddings/vision roles, "
        "env-seeded once. Dormant (404) while a feature's role is unconfigured."
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
    ),
    # The classifier node (spec 116 phase 2). Contributed, not hardcoded in
    # `automations` — which is the whole point of the node registry: a module
    # adds a node type to the canvas without the automations module learning it
    # exists, and disabling this plugin removes it from the palette in the same
    # breath. No dependency edge is needed either way: the node ships a spec and
    # a planner, and imports nothing from `automations` — the kernel is the only
    # thing both sides touch, which is what makes the seam a seam.
    # Spec 119 adds the second: `ai.validate`. Kept a separate module rather
    # than a mode on the classifier — one ROUTES (enumerated answers, cannot
    # invent a branch, says nothing in its own words) and one WRITES (prose
    # findings a person acts on), and a node that does both has to decide which
    # it is doing on every call.
    # Spec 120 adds the third: `ai.generate`. Kept separate from both for the
    # same reason they are separate from each other — one ROUTES on an
    # enumerated answer, one WRITES PROSE at a person, and this one FILLS IN
    # named values the rest of the graph reads. A node that did two of those
    # would have to decide which it was doing on every call.
    automation_nodes=(
        ai_automation_node.SPEC,
        ai_automation_node_validate.SPEC,
        ai_automation_node_generate.SPEC,
    ),
    # RADD-891: the feature toggles (Settings → AI) — moved off `settings.types`'s
    # old hardcoded dict. Every `AiFeature` member needs a row here AND both dicts
    # in `features.py`; `test_ai_features.py` asserts all three agree, because a
    # feature that reaches `feature_enabled` with no setting registered raises
    # KeyError at its call site (RADD-989: `mail_routing` shipped that way and every
    # llm mail rule fell through silently for a release).
    settings_keys=(
        SettingSpec(
            key="ai_editor_actions",
            section="ai",
            type="bool",
            scopes=("instance",),
            label="Editor AI actions",
            description=(
                "AI writing actions in the rich editor (/refine, /format, preset and "
                "freeform prompts) with streamed results and diff review. Also needs "
                "the chat role assigned; users can additionally opt out per profile."
            ),
        ),
        SettingSpec(
            key="ai_semantic_search",
            section="ai",
            type="bool",
            scopes=("instance",),
            label="Semantic search",
            description=(
                "Meaning-based retrieval fused into search, similar-issues, and the "
                "palette Ask mode. Needs the embeddings role assigned and the pgvector "
                "extension installed in Postgres."
            ),
        ),
        SettingSpec(
            key="ai_storage_routing",
            section="ai",
            type="bool",
            scopes=("instance",),
            label="LLM storage routing",
            description=(
                "Lets LLM-type storage routing rules classify uploads (Settings → "
                "Storage). Needs the vision role assigned; rules fall through to the "
                "next rule while this is off."
            ),
        ),
        SettingSpec(
            key="ai_mail_routing",
            section="ai",
            type="bool",
            scopes=("instance",),
            label="LLM mail routing",
            description=(
                "Lets AI-type mail routing rules pick the project a new message "
                "opens in from its content (Settings → Email). Needs the chat role "
                "assigned; rules fall through to the next rule while this is off."
            ),
        ),
        SettingSpec(
            key="ai_summarize",
            section="ai",
            type="bool",
            scopes=("instance",),
            label="Issue summarize",
            description="The Summarize action on issues (chat role).",
        ),
        SettingSpec(
            key="ai_nl_slq",
            section="ai",
            type="bool",
            scopes=("instance",),
            label="Natural language → SLQ",
            description="The Ask-AI bar that turns plain language into an SLQ filter (chat role).",
        ),
        SettingSpec(
            key="ai_similar_rerank",
            section="ai",
            type="bool",
            scopes=("instance",),
            label="Similar-issues LLM rerank",
            description=(
                "Rescore duplicate candidates with the chat model and explain why "
                "each looks related. Off by default — it costs a chat-model round "
                "trip per similar-issues open; similar issues keep working without "
                "it (FTS/vector candidates only)."
            ),
        ),
        SettingSpec(
            key="ai_validation",
            section="ai",
            type="bool",
            scopes=("instance",),
            label="AI intake checks",
            description=(
                "Lets the `AI check` automation node review a submission against "
                "a quality bar and report what falls short (spec 119). Needs the "
                "chat role assigned. Nothing runs until an admin puts the node in "
                "a validation graph, so this is the kill switch rather than the "
                "opt-in; off, the node takes its `unavailable` port."
            ),
        ),
        SettingSpec(
            key="ai_generation",
            section="ai",
            type="bool",
            scopes=("instance",),
            label="AI value generation",
            description=(
                "Lets the `Generate with AI` automation node work out named "
                "values about an item — a priority, a team, a sentence of "
                "advice — which downstream actions read as {{tokens}} (spec "
                "120). Needs the chat role assigned. Nothing runs until an "
                "admin puts the node in a graph, so this is the kill switch "
                "rather than the opt-in; off, the node takes its `unavailable` "
                "port and every token that would have read it skips its action."
            ),
        ),
        SettingSpec(
            key="ai_stream_responses",
            section="ai",
            type="bool",
            scopes=("instance",),
            label="Stream AI responses",
            description=(
                "Deliver issue summaries progressively and similar-issue candidates "
                "immediately with reasoning filled in as the model produces it. Off = "
                "each AI answer arrives complete, in one go."
            ),
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
)
