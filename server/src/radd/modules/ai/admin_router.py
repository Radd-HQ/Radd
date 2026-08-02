"""Settings → AI admin API (spec 101): providers, model roles, preset prompts.

Instance-admin only. Every write refreshes the process-local role snapshot the
sync capability check reads. Reads redact api_key (`has_api_key`); an empty key
on update means "keep the stored one".
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.exceptions import ForbiddenError
from radd.modules.auth.deps import CurrentUser
from radd.modules.auth.models import User
from radd.modules.auth.types import InstanceRole

from . import client, registry
from .registry import ResolvedModel
from .schemas import (
    AiPresetCreate,
    AiPresetRead,
    AiPresetUpdate,
    AiProviderCreate,
    AiProviderRead,
    AiProviderUpdate,
    AiRoleAssign,
    AiRoleRead,
)
from .types import AiRole, AiUpstreamError, AiWireShape

router = APIRouter(prefix="/ai", tags=["ai admin"])

Session = Annotated[AsyncSession, Depends(get_session)]


def _require_instance_admin(actor: User) -> None:
    if InstanceRole(actor.instance_role) is not InstanceRole.ADMIN:
        raise ForbiddenError("AI settings require an instance admin")


# --- providers ----------------------------------------------------------------


@router.get("/providers", response_model=list[AiProviderRead])
async def list_providers(session: Session, user: CurrentUser) -> list[AiProviderRead]:
    _require_instance_admin(user)
    return [AiProviderRead.model_validate(p) for p in await registry.list_providers(session)]


@router.post("/providers", response_model=AiProviderRead, status_code=201)
async def create_provider(
    data: AiProviderCreate, session: Session, user: CurrentUser
) -> AiProviderRead:
    _require_instance_admin(user)
    provider = await registry.create_provider(session, data)
    await registry.refresh_snapshot(session)
    return AiProviderRead.model_validate(provider)


@router.patch("/providers/{provider_id}", response_model=AiProviderRead)
async def update_provider(
    provider_id: uuid.UUID, data: AiProviderUpdate, session: Session, user: CurrentUser
) -> AiProviderRead:
    _require_instance_admin(user)
    provider = await registry.update_provider(session, provider_id, data)
    await registry.refresh_snapshot(session)
    return AiProviderRead.model_validate(provider)


@router.delete("/providers/{provider_id}", status_code=204)
async def delete_provider(provider_id: uuid.UUID, session: Session, user: CurrentUser) -> Response:
    _require_instance_admin(user)
    await registry.delete_provider(session, provider_id)
    await registry.refresh_snapshot(session)
    return Response(status_code=204)


class ProbeResult(BaseModel):
    ok: bool
    error: str = ""
    latency_ms: float | None = None


@router.post("/providers/{provider_id}/test", response_model=ProbeResult)
async def test_provider(provider_id: uuid.UUID, session: Session, user: CurrentUser) -> ProbeResult:
    """One max_tokens=1 completion against the row's default model — failures
    come back as data (the admin is diagnosing config), never a 502."""
    _require_instance_admin(user)
    row = await registry.get_provider(session, provider_id)
    shape = AiWireShape(row.wire_shape)
    model = row.default_model
    if not model and shape is AiWireShape.LOCAL:
        from .localembed import DEFAULT_LOCAL_MODEL

        model = DEFAULT_LOCAL_MODEL
    if not model:
        return ProbeResult(ok=False, error="set a default model to test this provider")
    resolved = ResolvedModel(
        wire_shape=shape, base_url=row.base_url, api_key=row.api_key, model=model
    )
    try:
        latency = await client.probe(resolved)
    except AiUpstreamError as exc:
        return ProbeResult(ok=False, error=str(exc))
    return ProbeResult(ok=True, latency_ms=round(latency, 1))


class EmbeddingCoverage(BaseModel):
    enabled: bool
    items_total: int = 0
    items_embedded: int = 0
    docs_total: int = 0
    docs_embedded: int = 0


@router.get("/embeddings/coverage", response_model=EmbeddingCoverage)
async def embeddings_coverage(session: Session, user: CurrentUser) -> EmbeddingCoverage:
    """How much of the corpus the active embedding model has indexed — the
    backfill's progress bar (spec 103)."""
    from .embeddings import service as embeddings_service
    from .types import AiRole as _AiRole

    _require_instance_admin(user)
    if not await embeddings_service.vector_available(session):
        return EmbeddingCoverage(enabled=False)
    resolved = await registry.resolve_role(session, _AiRole.EMBEDDINGS)
    if resolved is None:
        return EmbeddingCoverage(enabled=False)
    from .embeddings import embedder as embeddings_embedder

    counts = await embeddings_service.coverage(session, model=resolved.model)
    return EmbeddingCoverage(
        enabled=True, last_error=embeddings_embedder.last_error(), **counts
    )


class LocalEmbedInfo(BaseModel):
    available: bool
    default_model: str
    models: list[dict]


@router.get("/local-embed", response_model=LocalEmbedInfo)
async def local_embed_info(user: CurrentUser) -> LocalEmbedInfo:
    """Whether the built-in CPU embedding backend is installed, and its model
    catalog (feeds the LOCAL provider form's model picker)."""
    from . import localembed

    _require_instance_admin(user)
    return LocalEmbedInfo(
        available=localembed.available(),
        default_model=localembed.DEFAULT_LOCAL_MODEL,
        models=localembed.supported_models(),
    )


# --- roles --------------------------------------------------------------------


@router.get("/roles", response_model=list[AiRoleRead])
async def list_roles(session: Session, user: CurrentUser) -> list[AiRoleRead]:
    _require_instance_admin(user)
    return [
        AiRoleRead(
            role=AiRole(row.role),
            provider_id=provider.id,
            provider_name=provider.name,
            model=row.model,
            effective_model=row.model or provider.default_model,
        )
        for row, provider in await registry.list_roles(session)
    ]


@router.put("/roles/{role}", response_model=AiRoleRead)
async def set_role(
    role: AiRole, data: AiRoleAssign, session: Session, user: CurrentUser
) -> AiRoleRead:
    _require_instance_admin(user)
    row = await registry.set_role(session, role, data)
    provider = await registry.get_provider(session, row.provider_id)
    await registry.refresh_snapshot(session)
    return AiRoleRead(
        role=role,
        provider_id=provider.id,
        provider_name=provider.name,
        model=row.model,
        effective_model=row.model or provider.default_model,
    )


@router.delete("/roles/{role}", status_code=204)
async def clear_role(role: AiRole, session: Session, user: CurrentUser) -> Response:
    _require_instance_admin(user)
    await registry.clear_role(session, role)
    await registry.refresh_snapshot(session)
    return Response(status_code=204)


# --- preset prompts -----------------------------------------------------------


@router.get("/presets", response_model=list[AiPresetRead])
async def list_presets(session: Session, user: CurrentUser) -> list[AiPresetRead]:
    _require_instance_admin(user)
    return [AiPresetRead.model_validate(p) for p in await registry.list_presets(session)]


@router.post("/presets", response_model=AiPresetRead, status_code=201)
async def create_preset(data: AiPresetCreate, session: Session, user: CurrentUser) -> AiPresetRead:
    _require_instance_admin(user)
    return AiPresetRead.model_validate(await registry.create_preset(session, data))


@router.patch("/presets/{preset_id}", response_model=AiPresetRead)
async def update_preset(
    preset_id: uuid.UUID, data: AiPresetUpdate, session: Session, user: CurrentUser
) -> AiPresetRead:
    _require_instance_admin(user)
    return AiPresetRead.model_validate(await registry.update_preset(session, preset_id, data))


@router.delete("/presets/{preset_id}", status_code=204)
async def delete_preset(preset_id: uuid.UUID, session: Session, user: CurrentUser) -> Response:
    _require_instance_admin(user)
    await registry.delete_preset(session, preset_id)
    return Response(status_code=204)
