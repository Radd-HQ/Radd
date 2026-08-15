"""Wire a FRESH database up to the dev machine's infrastructure.

A clean database is not a usable instance: storage hosts, the routing chain, the
AI providers and the per-feature toggles are all DB rows, so an empty schema has
no storage, no LLM and every AI feature dark. This turns `alembic upgrade head`
into something you can actually open.

Everything here is IDEMPOTENT — it find-or-creates — so running it twice is safe
and re-running it after a partial failure finishes the job rather than doubling
it.

Machine-specific by design: the endpoints below are Hussein's dev box. It is a
dev seeder, not deploy configuration; a real instance configures these in
Settings, and `RADD_SEED_*` overrides every value for anyone else.

Usage (from `server/`):
    uv run python scripts/seed_dev_stack.py
"""

from __future__ import annotations

import asyncio
import os

from sqlalchemy import select

from radd.config import settings as app_settings
from radd.db import SessionLocal
from radd.kernel import load_plugins
from radd.modules.ai.models import AiModelRole, AiProviderRow
from radd.modules.ai.types import AiRole, AiWireShape
from radd.modules.attachments import hosts as storage_hosts
from radd.modules.attachments.models import StorageHost, StorageRule
from radd.modules.attachments.schemas import StorageHostCreate
from radd.modules.attachments.types import DeliveryMode, RuleType, StorageHostType
from radd.modules.settings import service as settings_service
from radd.modules.settings.types import SettingKey, SettingScope

# --- the dev box's infrastructure --------------------------------------------

#: Fixed dev credentials, imported into both Garage nodes by
#: `deploy/garage/init.sh`. Dev-only and in the repo already.
GARAGE_ACCESS = "GK647261646464657630313233"
GARAGE_SECRET = "6472616464646576736563726574303030303030303030303030303030303030"
GARAGE_BUCKET = "radd-dev"
#: Garage signs against its OWN `s3_region`, so this must match `garage.toml`.
#: A mismatch is a SignatureDoesNotMatch on every upload, which reads as bad
#: credentials rather than as the region being wrong.
GARAGE_REGION = "garage"

CONTENT_ENDPOINT = os.environ.get("RADD_SEED_CONTENT_ENDPOINT", "localhost:3920")
GENERAL_ENDPOINT = os.environ.get("RADD_SEED_GENERAL_ENDPOINT", "localhost:3930")

#: An OpenAI-compatible chat/vision endpoint (vLLM, Ollama, …). No default:
#: point RADD_SEED_LLM_BASE_URL at yours (put it in .env — it is machine-local),
#: or the seed skips chat/vision wiring and says so.
LLM_BASE_URL = os.environ.get("RADD_SEED_LLM_BASE_URL", "")
LLM_MODEL = os.environ.get("RADD_SEED_LLM_MODEL", "gemma-4-31b-it")
LLM_NAME = os.environ.get("RADD_SEED_LLM_NAME", "Dev LLM")

#: Text-embeddings-inference, the GPU profile in compose.dev.yaml. Serving the
#: same model the built-in CPU backend used keeps already-embedded vectors valid.
EMBED_BASE_URL = os.environ.get("RADD_SEED_EMBED_BASE_URL", "http://localhost:8081/v1")
EMBED_MODEL = os.environ.get("RADD_SEED_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
EMBED_NAME = "Embeddings (TEI)"

#: Every AI feature, on. A clean instance exists to exercise them.
AI_TOGGLES = (
    SettingKey.AI_EDITOR_ACTIONS,
    SettingKey.AI_SEMANTIC_SEARCH,
    SettingKey.AI_STORAGE_ROUTING,
    SettingKey.AI_MAIL_ROUTING,
    SettingKey.AI_SUMMARIZE,
    SettingKey.AI_NL_SLQ,
    SettingKey.AI_SIMILAR_RERANK,
)


async def _storage(session) -> None:
    """Two S3 hosts, plus the routing chain that makes having two mean something."""
    for name, endpoint, is_default, selectable in (
        ("Content", CONTENT_ENDPOINT, True, False),
        ("General", GENERAL_ENDPOINT, False, True),
    ):
        existing = await session.scalar(select(StorageHost).where(StorageHost.name == name))
        if existing is not None:
            print(f"  storage host {name!r} already there")
            continue
        await storage_hosts.create_host(
            session,
            StorageHostCreate(
                name=name,
                host_type=StorageHostType.S3,
                endpoint=endpoint,
                access_key=GARAGE_ACCESS,
                secret_key=GARAGE_SECRET,
                bucket=GARAGE_BUCKET,
                region=GARAGE_REGION,
                secure=False,
                delivery_mode=DeliveryMode.PROXY,
                user_selectable=selectable,
                is_default=is_default,
            ),
        )
        print(f"  storage host {name!r} -> {endpoint}")

    content = await session.scalar(select(StorageHost).where(StorageHost.name == "Content"))
    rules = (
        # An LLM rule first: it is the one that needs the vision role, so having
        # it here is what makes "is storage routing actually wired?" answerable.
        ("Content", RuleType.LLM, 1, {"host_id": str(content.id) if content else "",
                               "prompt": "Is this image production content (frames, "
                                         "plates, renders) or a general document?",
                               "answers": {"content": str(content.id) if content else ""}}),
        ("Content Ask", RuleType.USER_CHOICE, 2, {}),
    )
    for name, rule_type, position, config in rules:
        existing = await session.scalar(select(StorageRule).where(StorageRule.name == name))
        if existing is not None:
            print(f"  routing rule {name!r} already there")
            continue
        session.add(
            StorageRule(
                name=name, rule_type=rule_type.value, position=position, config=config
            )
        )
        print(f"  routing rule {name!r} ({rule_type.value}, position {position})")
    await session.flush()


async def _provider(session, *, name: str, base_url: str, model: str) -> AiProviderRow:
    row = await session.scalar(select(AiProviderRow).where(AiProviderRow.name == name))
    if row is not None:
        print(f"  provider {name!r} already there")
        return row
    row = AiProviderRow(
        name=name,
        wire_shape=AiWireShape.OPENAI.value,
        base_url=base_url,
        api_key="",
        default_model=model,
    )
    session.add(row)
    await session.flush()
    print(f"  provider {name!r} -> {base_url} ({model})")
    return row


async def _ai(session) -> None:
    """The providers, the role assignments, and the feature toggles.

    A feature is live only when its toggle is ON **and** its role resolves to a
    provider (`ai/features.py`), so seeding one without the other leaves the UI
    claiming a capability that quietly does nothing.
    """
    embed = await _provider(session, name=EMBED_NAME, base_url=EMBED_BASE_URL, model=EMBED_MODEL)
    roles: list[tuple[AiRole, object, str]] = [(AiRole.EMBEDDINGS, embed, EMBED_MODEL)]
    if LLM_BASE_URL:
        # chat + vision on the LLM (assumed vision-capable); embeddings stay on
        # TEI, which is the only one of the two that serves them.
        llm = await _provider(session, name=LLM_NAME, base_url=LLM_BASE_URL, model=LLM_MODEL)
        roles = [(AiRole.CHAT, llm, LLM_MODEL), (AiRole.VISION, llm, LLM_MODEL), *roles]
    else:
        print("  RADD_SEED_LLM_BASE_URL unset — skipping chat/vision provider wiring")
    for role, provider, model in roles:
        existing = await session.get(AiModelRole, role.value)
        if existing is not None:
            print(f"  role {role.value} already assigned")
            continue
        session.add(AiModelRole(role=role.value, provider_id=provider.id, model=model))
        print(f"  role {role.value} -> {provider.name}")
    await session.flush()

    for key in AI_TOGGLES:
        await settings_service.set_value(
            session, key, SettingScope.INSTANCE, None, True
        )
    print(f"  {len(AI_TOGGLES)} AI feature toggles on")


async def main() -> None:
    # The contribution registries are BOOT STATE — `create_app()` fills them by
    # calling `load_plugins`, and a standalone script does not. Without this,
    # `settings_service.set_value` raises KeyError on a key whose spec no plugin
    # has registered yet, which reads as "that setting does not exist".
    load_plugins(app_settings.modules)

    async with SessionLocal() as session:
        print("storage:")
        await _storage(session)
        print("ai:")
        await _ai(session)
        await session.commit()
    print("done — storage hosts, routing chain, AI providers and toggles are live")


if __name__ == "__main__":
    asyncio.run(main())
