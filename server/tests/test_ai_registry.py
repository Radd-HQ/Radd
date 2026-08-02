"""AI provider registry (spec 101) — DB-managed providers + model roles.

The invariants the AI features lean on: a role resolves to a callable
`ResolvedModel` or cleanly to None (dormant), the embeddings role can never
point at an Anthropic-shaped provider (no embeddings API there), a stored key
survives a round-trip through the redacted read shape, and env seeding happens
once.

CRUD tests are flushed, never committed; the session rolls back at teardown.
`seed_from_env` opens its OWN session and commits (startup hook), so its test
cleans up explicitly.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.db import SessionLocal
from radd.exceptions import ConflictError
from radd.modules.ai import registry
from radd.modules.ai.schemas import (
    AiProviderCreate,
    AiProviderUpdate,
    AiRoleAssign,
)
from radd.modules.ai.types import AiConfigError, AiProviderSource, AiRole, AiWireShape


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


def _create(name: str = "", **overrides) -> AiProviderCreate:
    payload = {
        "name": name or f"ai-{uuid.uuid4().hex[:8]}",
        "wire_shape": AiWireShape.OPENAI,
        "base_url": "http://vllm.local:8000/v1",
        "api_key": "key-1",
        "default_model": "gemma",
    }
    payload.update(overrides)
    return AiProviderCreate(**payload)


# --- role resolution ----------------------------------------------------------


async def test_role_resolves_with_role_model_over_provider_default(db):
    provider = await registry.create_provider(db, _create(default_model="gemma"))
    await registry.set_role(
        db, AiRole.CHAT, AiRoleAssign(provider_id=provider.id, model="qwen3")
    )
    resolved = await registry.resolve_role(db, AiRole.CHAT)
    assert resolved is not None
    assert resolved.model == "qwen3"
    assert resolved.wire_shape is AiWireShape.OPENAI
    assert resolved.api_key == "key-1"


async def test_role_falls_back_to_the_provider_default_model(db):
    provider = await registry.create_provider(db, _create(default_model="gemma"))
    await registry.set_role(db, AiRole.VISION, AiRoleAssign(provider_id=provider.id))
    resolved = await registry.resolve_role(db, AiRole.VISION)
    assert resolved is not None and resolved.model == "gemma"


async def test_unassigned_role_resolves_to_none(db):
    await db.execute(text("DELETE FROM ai_model_roles"))
    assert await registry.resolve_role(db, AiRole.EMBEDDINGS) is None


async def test_role_with_no_model_anywhere_is_not_callable(db):
    """Assigned but nameless — resolve must refuse rather than send model=''."""
    provider = await registry.create_provider(db, _create(default_model=""))
    await registry.set_role(db, AiRole.CHAT, AiRoleAssign(provider_id=provider.id, model=""))
    assert await registry.resolve_role(db, AiRole.CHAT) is None


# --- the embeddings/anthropic guard ------------------------------------------


async def test_embeddings_role_rejects_an_anthropic_provider(db):
    provider = await registry.create_provider(
        db, _create(wire_shape=AiWireShape.ANTHROPIC, default_model="claude")
    )
    with pytest.raises(AiConfigError):
        await registry.set_role(db, AiRole.EMBEDDINGS, AiRoleAssign(provider_id=provider.id))


async def test_provider_cannot_flip_to_anthropic_while_holding_embeddings(db):
    provider = await registry.create_provider(db, _create(default_model="bge-m3"))
    await registry.set_role(db, AiRole.EMBEDDINGS, AiRoleAssign(provider_id=provider.id))
    with pytest.raises(AiConfigError):
        await registry.update_provider(
            db, provider.id, AiProviderUpdate(wire_shape=AiWireShape.ANTHROPIC)
        )


# --- the built-in local embedding backend (spec 101 addendum) -----------------


async def test_local_provider_embeds_only(db):
    """LOCAL holds the embeddings role and nothing else; endpoint/key refused."""
    provider = await registry.create_provider(
        db, _create(wire_shape=AiWireShape.LOCAL, base_url="", api_key="", default_model="")
    )
    with pytest.raises(AiConfigError):
        await registry.set_role(db, AiRole.CHAT, AiRoleAssign(provider_id=provider.id))
    with pytest.raises(AiConfigError):
        await registry.set_role(db, AiRole.VISION, AiRoleAssign(provider_id=provider.id))
    await registry.set_role(db, AiRole.EMBEDDINGS, AiRoleAssign(provider_id=provider.id))
    resolved = await registry.resolve_role(db, AiRole.EMBEDDINGS)
    assert resolved is not None
    assert resolved.wire_shape is AiWireShape.LOCAL
    from radd.modules.ai.localembed import DEFAULT_LOCAL_MODEL

    assert resolved.model == DEFAULT_LOCAL_MODEL  # nameless LOCAL gets the default
    with pytest.raises(AiConfigError):
        await registry.create_provider(
            db,
            _create(wire_shape=AiWireShape.LOCAL, base_url="http://nope", default_model=""),
        )


async def test_local_embed_dispatch(db, monkeypatch):
    """client.embed routes LOCAL rows to the built-in backend, not HTTP."""
    from radd.modules.ai import client, localembed

    provider = await registry.create_provider(
        db, _create(wire_shape=AiWireShape.LOCAL, base_url="", api_key="", default_model="")
    )
    await registry.set_role(db, AiRole.EMBEDDINGS, AiRoleAssign(provider_id=provider.id))
    seen: dict = {}

    async def fake_embed(model, texts):
        seen["model"] = model
        return [[0.1, 0.2] for _ in texts]

    monkeypatch.setattr(localembed, "embed_texts", fake_embed)
    vectors = await client.embed(db, AiRole.EMBEDDINGS, ["a", "b"])
    assert vectors == [[0.1, 0.2], [0.1, 0.2]]
    assert seen["model"] == localembed.DEFAULT_LOCAL_MODEL


# --- provider CRUD invariants -------------------------------------------------


async def test_update_with_empty_api_key_keeps_the_stored_one(db):
    provider = await registry.create_provider(db, _create(api_key="secret"))
    await registry.update_provider(
        db, provider.id, AiProviderUpdate(api_key=registry.UNCHANGED_CREDENTIAL, name="renamed")
    )
    assert provider.api_key == "secret"
    assert provider.name == "renamed"


async def test_duplicate_provider_name_conflicts(db):
    await registry.create_provider(db, _create("dup"))
    with pytest.raises(ConflictError):
        await registry.create_provider(db, _create("dup"))


async def test_deleting_a_provider_cascades_its_roles(db):
    provider = await registry.create_provider(db, _create())
    await registry.set_role(db, AiRole.CHAT, AiRoleAssign(provider_id=provider.id, model="m"))
    await registry.delete_provider(db, provider.id)
    db.expire_all()
    assert await registry.resolve_role(db, AiRole.CHAT) is None


# --- env seeding --------------------------------------------------------------


async def test_seed_from_env_creates_provider_and_chat_role_once(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "openai")
    monkeypatch.setattr(settings, "ai_base_url", "http://ollama.local:11434/v1")
    monkeypatch.setattr(settings, "ai_api_key", "seed-key")
    monkeypatch.setattr(settings, "ai_model", "gemma")
    async with SessionLocal() as session:
        await session.execute(text("DELETE FROM ai_model_roles"))
        await session.execute(text("DELETE FROM ai_providers"))
        await session.commit()
    try:
        await registry.seed_from_env()
        await registry.seed_from_env()  # second boot: no duplicate
        async with SessionLocal() as session:
            providers = await registry.list_providers(session)
            assert len(providers) == 1
            assert providers[0].name == "ollama.local"
            assert providers[0].source == AiProviderSource.ENV.value
            resolved = await registry.resolve_role(session, AiRole.CHAT)
            assert resolved is not None and resolved.model == "gemma"
            # The startup snapshot now serves the sync capability check.
            assert registry.role_snapshot()[AiRole.CHAT.value]["model"] == "gemma"
    finally:
        async with SessionLocal() as session:
            await session.execute(text("DELETE FROM ai_model_roles"))
            await session.execute(text("DELETE FROM ai_providers"))
            await session.commit()


async def test_seed_from_env_is_inert_without_configuration(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "")
    async with SessionLocal() as session:
        await session.execute(text("DELETE FROM ai_model_roles"))
        await session.execute(text("DELETE FROM ai_providers"))
        await session.commit()
    await registry.seed_from_env()
    async with SessionLocal() as session:
        assert await registry.list_providers(session) == []
