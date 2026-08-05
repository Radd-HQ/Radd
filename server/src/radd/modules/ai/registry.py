"""AI provider registry (spec 101) — providers, model roles, presets, env seeding.

Every feature resolves a ROLE (chat | embeddings | vision) through here and then
works from a `ResolvedModel` value object, never the ORM row — network calls
must not hold session state. The env `ai_*` settings survive as seed-only input
(the jiraimport-connections pattern): they create one provider row on first
boot, after which everything is UI-managed.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import SessionLocal
from radd.snapshot import Snapshot
from radd.exceptions import ConflictError, NotFoundError

from .models import AiModelRole, AiPresetPrompt, AiProviderRow
from .schemas import (
    AiPresetCreate,
    AiPresetUpdate,
    AiProviderCreate,
    AiProviderUpdate,
    AiRoleAssign,
)
from .types import AiConfigError, AiDisabledError, AiEntity, AiProviderSource, AiRole, AiWireShape

logger = logging.getLogger(__name__)

# Update payloads leave the credential alone when this is what came in — a form
# that round-trips a redacted read must not blank the stored key.
UNCHANGED_CREDENTIAL = ""


@dataclass(frozen=True)
class ResolvedModel:
    """Everything a network call needs for one role. A value object, never the row."""

    wire_shape: AiWireShape
    base_url: str
    api_key: str
    model: str


# --- providers ----------------------------------------------------------------


async def list_providers(session: AsyncSession) -> list[AiProviderRow]:
    result = await session.execute(select(AiProviderRow).order_by(AiProviderRow.name))
    return list(result.scalars())


async def get_provider(session: AsyncSession, provider_id: uuid.UUID) -> AiProviderRow:
    provider = await session.get(AiProviderRow, provider_id)
    if provider is None:
        raise NotFoundError(AiEntity.PROVIDER, provider_id)
    return provider


async def create_provider(
    session: AsyncSession,
    data: AiProviderCreate,
    *,
    source: AiProviderSource = AiProviderSource.USER,
) -> AiProviderRow:
    await _ensure_name_free(session, data.name)
    if data.wire_shape is AiWireShape.LOCAL:
        _validate_local_shape(data)
    provider = AiProviderRow(
        name=data.name,
        wire_shape=data.wire_shape.value,
        base_url=data.base_url.rstrip("/"),
        api_key=data.api_key,
        default_model=data.default_model,
        source=source.value,
    )
    session.add(provider)
    await session.flush()
    return provider


async def update_provider(
    session: AsyncSession, provider_id: uuid.UUID, data: AiProviderUpdate
) -> AiProviderRow:
    provider = await get_provider(session, provider_id)
    fields = data.model_dump(exclude_unset=True)
    if "name" in fields and fields["name"] != provider.name:
        await _ensure_name_free(session, fields["name"])
        provider.name = fields["name"]
    if "wire_shape" in fields:
        new_shape = AiWireShape(fields["wire_shape"])
        if new_shape is AiWireShape.ANTHROPIC:
            await _reject_embeddings_assignment(session, provider.id)
        provider.wire_shape = new_shape.value
    if "base_url" in fields:
        provider.base_url = fields["base_url"].rstrip("/")
    # An empty key means "keep the stored one" — the read shape is redacted.
    if fields.get("api_key"):
        provider.api_key = fields["api_key"]
    if "default_model" in fields:
        provider.default_model = fields["default_model"]
    await session.flush()
    return provider


async def delete_provider(session: AsyncSession, provider_id: uuid.UUID) -> None:
    provider = await get_provider(session, provider_id)
    # Role rows cascade away in the DB; the ORM delete keeps it explicit.
    await session.delete(provider)
    await session.flush()


async def _ensure_name_free(session: AsyncSession, name: str) -> None:
    result = await session.execute(select(AiProviderRow).where(AiProviderRow.name == name))
    if result.scalar_one_or_none() is not None:
        raise ConflictError(AiEntity.PROVIDER, reason=f"a provider named {name!r} exists")


# --- roles --------------------------------------------------------------------


async def list_roles(session: AsyncSession) -> list[tuple[AiModelRole, AiProviderRow]]:
    result = await session.execute(
        select(AiModelRole, AiProviderRow).join(
            AiProviderRow, AiModelRole.provider_id == AiProviderRow.id
        )
    )
    return [(role, provider) for role, provider in result.all()]


def _check_local_model(model: str) -> None:
    """Refuse a model the built-in backend cannot load (RADD-723).

    `BAA/bge-small-en-v1.5` — one character short of `BAAI/…` — was accepted,
    and then raised on EVERY embedder iteration for the life of the instance
    while every dashboard read healthy. The supported list is already published
    for the admin UI; checking against it one step earlier turns a permanent
    silent outage into a 422 naming the valid models.
    """
    from . import localembed

    if not model or not localembed.available():
        return  # the extra is absent; embed_texts raises a clear error of its own
    supported = {entry["model"] for entry in localembed.supported_models()}
    if model not in supported:
        raise AiConfigError(
            f"the built-in backend has no model {model!r}. Available: "
            + ", ".join(sorted(supported)[:8])
            + ("…" if len(supported) > 8 else "")
        )


async def set_role(session: AsyncSession, role: AiRole, data: AiRoleAssign) -> AiModelRole:
    provider = await get_provider(session, data.provider_id)
    if role is AiRole.EMBEDDINGS and provider.wire_shape == AiWireShape.ANTHROPIC.value:
        raise AiConfigError(
            "the embeddings role needs an OpenAI-compatible or built-in provider "
            "(the Anthropic API has no embeddings endpoint)"
        )
    if role is not AiRole.EMBEDDINGS and provider.wire_shape == AiWireShape.LOCAL.value:
        raise AiConfigError(
            "the built-in local backend only embeds — chat and vision need a real endpoint"
        )
    if provider.wire_shape == AiWireShape.LOCAL.value:
        _check_local_model(data.model or provider.default_model)
    row = await session.get(AiModelRole, role.value)
    if row is None:
        row = AiModelRole(role=role.value, provider_id=provider.id, model=data.model)
        session.add(row)
    else:
        row.provider_id = provider.id
        row.model = data.model
    await session.flush()
    return row


async def clear_role(session: AsyncSession, role: AiRole) -> None:
    row = await session.get(AiModelRole, role.value)
    if row is None:
        raise NotFoundError(AiEntity.ROLE, role.value)
    await session.delete(row)
    await session.flush()


async def _reject_embeddings_assignment(session: AsyncSession, provider_id: uuid.UUID) -> None:
    """Flipping a provider to anthropic must not strand an embeddings assignment."""
    row = await session.get(AiModelRole, AiRole.EMBEDDINGS.value)
    if row is not None and row.provider_id == provider_id:
        raise AiConfigError(
            "this provider holds the embeddings role, which needs an "
            "OpenAI-compatible endpoint — reassign the role first"
        )


def _validate_local_shape(data: AiProviderCreate) -> None:
    """A LOCAL provider needs the optional extra installed, and carries no
    endpoint/key — refuse config that pretends otherwise."""
    from . import localembed

    if not localembed.available():
        raise AiConfigError(
            "built-in embeddings need the localembed extra (pip install 'radd[localembed]')"
        )
    if data.base_url or data.api_key:
        raise AiConfigError("the built-in local backend takes no base_url or api_key")


async def resolve_role(session: AsyncSession, role: AiRole) -> ResolvedModel | None:
    """The callable model for a role, or None when unconfigured (feature dormant)."""
    result = await session.execute(
        select(AiModelRole, AiProviderRow)
        .join(AiProviderRow, AiModelRole.provider_id == AiProviderRow.id)
        .where(AiModelRole.role == role.value)
    )
    pair = result.first()
    if pair is None:
        return None
    row, provider = pair
    model = row.model or provider.default_model
    if not model and provider.wire_shape == AiWireShape.LOCAL.value:
        from .localembed import DEFAULT_LOCAL_MODEL

        model = DEFAULT_LOCAL_MODEL
    if not model:
        return None  # assigned but no model named anywhere — not callable
    return ResolvedModel(
        wire_shape=AiWireShape(provider.wire_shape),
        base_url=provider.base_url,
        api_key=provider.api_key,
        model=model,
    )


async def require_role(session: AsyncSession, role: AiRole) -> ResolvedModel:
    resolved = await resolve_role(session, role)
    if resolved is None:
        raise AiDisabledError()  # -> the 404-dormant handler
    return resolved


# --- presets ------------------------------------------------------------------


async def list_presets(
    session: AsyncSession, *, enabled_only: bool = False
) -> list[AiPresetPrompt]:
    query = select(AiPresetPrompt).order_by(AiPresetPrompt.position, AiPresetPrompt.name)
    if enabled_only:
        query = query.where(AiPresetPrompt.enabled)
    result = await session.execute(query)
    return list(result.scalars())


async def get_preset(session: AsyncSession, preset_id: uuid.UUID) -> AiPresetPrompt:
    preset = await session.get(AiPresetPrompt, preset_id)
    if preset is None:
        raise NotFoundError(AiEntity.PRESET, preset_id)
    return preset


async def create_preset(session: AsyncSession, data: AiPresetCreate) -> AiPresetPrompt:
    preset = AiPresetPrompt(
        name=data.name, prompt=data.prompt, enabled=data.enabled, position=data.position
    )
    session.add(preset)
    await session.flush()
    return preset


async def update_preset(
    session: AsyncSession, preset_id: uuid.UUID, data: AiPresetUpdate
) -> AiPresetPrompt:
    preset = await get_preset(session, preset_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(preset, field, value)
    await session.flush()
    return preset


async def delete_preset(session: AsyncSession, preset_id: uuid.UUID) -> None:
    preset = await get_preset(session, preset_id)
    await session.delete(preset)
    await session.flush()


# --- capability snapshot ------------------------------------------------------

# CapabilitySpec.check is sync; it cannot query. This process-local snapshot of
# {role: {"provider": name, "model": model}} is write-through on admin edits +
# startup and TTL'd (RADD-899), so a second web replica converges within
# settings.snapshot_ttl_seconds instead of at its next restart. Real work paths
# still resolve from the DB.


def _roles_of(pairs) -> dict[str, dict[str, str]]:
    return {
        row.role: {"provider": provider.name, "model": row.model or provider.default_model}
        for row, provider in pairs
    }


async def _load_role_snapshot() -> dict[str, dict[str, str]]:
    async with SessionLocal() as session:
        return _roles_of(await list_roles(session))


_role_snapshot: Snapshot[dict[str, dict[str, str]]] = Snapshot(
    "ai.roles", _load_role_snapshot, initial={}
)


def role_snapshot() -> dict[str, dict[str, str]]:
    return dict(_role_snapshot.get())


async def refresh_snapshot(session: AsyncSession) -> None:
    _role_snapshot.set(_roles_of(await list_roles(session)))


# --- env seeding (startup) ----------------------------------------------------


async def seed_from_env() -> None:
    """Turn a spec-46 environment configuration into a provider row + chat role, ONCE.

    Runs only when the table is empty, so an admin who deletes the seeded row
    never has it silently reappear. Seeded rows are ordinary editable providers.
    """
    async with SessionLocal() as session:
        existing = await session.execute(select(AiProviderRow.id).limit(1))
        if existing.first() is None:
            await _seed_provider(session)
            await session.commit()
        await refresh_snapshot(session)


async def _seed_provider(session: AsyncSession) -> None:
    try:
        shape = AiWireShape(settings.ai_provider) if settings.ai_provider else None
    except ValueError:
        shape = None
    if shape is None:
        return
    provider = await create_provider(
        session,
        AiProviderCreate(
            name=_seed_name(shape, settings.ai_base_url),
            wire_shape=shape,
            base_url=settings.ai_base_url,
            api_key=settings.ai_api_key,
            default_model=settings.ai_model,
        ),
        source=AiProviderSource.ENV,
    )
    if settings.ai_model:
        await set_role(
            session, AiRole.CHAT, AiRoleAssign(provider_id=provider.id, model=settings.ai_model)
        )
    logger.info("ai: seeded provider %r (chat role) from the environment", provider.name)


def _seed_name(shape: AiWireShape, base_url: str) -> str:
    """Name the seeded row after its host so several providers over time read sensibly."""
    host = base_url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    if host:
        return host
    return "Anthropic" if shape is AiWireShape.ANTHROPIC else "OpenAI-compatible"
