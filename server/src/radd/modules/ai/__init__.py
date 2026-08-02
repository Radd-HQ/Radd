from fastapi import Request
from fastapi.responses import JSONResponse

from radd.kernel import CapabilitySpec
from radd.kernel import RaddPlugin

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


plugin = RaddPlugin(
    name="ai",
    core=False,  # optional plugin — disableable via the plugin manager
    description=(
        "Optional provider-agnostic AI: item summarize, similar-item duplicate "
        "candidates (FTS-first, LLM rerank), NL->SLQ (spec 46), plus the provider "
        "registry (spec 101): DB provider rows + chat/embeddings/vision roles, "
        "env-seeded once. Dormant (404) while a feature's role is unconfigured."
    ),
    depends_on=("auth", "projects", "items", "fields", "comments", "search", "settings"),
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
