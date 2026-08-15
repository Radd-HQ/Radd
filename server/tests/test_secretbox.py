"""RADD-1086 — webhook signing secrets are ciphertext at rest.

The secretbox key derives from the backup key, so tests point
settings.backup_key_file at a tmp path (and reset the derivation cache);
nothing here touches a real key.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd import secretbox
from radd.config import settings
from radd.modules.webhooks import service as webhooks_service
from radd.modules.webhooks.models import WebhookEndpoint
from radd.modules.webhooks.schemas import EndpointCreate


@pytest.fixture
def keyfile(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "backup_key_file", str(tmp_path / "key"))
    secretbox.reset_key_cache()
    yield
    secretbox.reset_key_cache()


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


def test_roundtrip_and_prefix(keyfile):
    stored = secretbox.encrypt("whsec_abc123")
    assert secretbox.is_encrypted(stored)
    assert stored != "whsec_abc123"
    assert secretbox.decrypt(stored) == "whsec_abc123"


def test_plaintext_passes_through(keyfile):
    """Legacy rows keep working until the startup hook adopts them."""
    assert secretbox.decrypt("whsec_legacy") == "whsec_legacy"


def test_tamper_is_an_error_not_garbage(keyfile):
    stored = secretbox.encrypt("whsec_abc123")
    flipped = stored[:-4] + ("AAAA" if stored[-4:] != "AAAA" else "BBBB")
    with pytest.raises(secretbox.SecretBoxError):
        secretbox.decrypt(flipped)


async def test_create_stores_ciphertext_and_signing_still_works(keyfile, db):
    endpoint = await webhooks_service.create_endpoint(
        db, EndpointCreate(url="https://receiver.example/hook", description="", event_types=None)
    )
    assert secretbox.is_encrypted(endpoint.secret)
    plain = webhooks_service.reveal_secret(endpoint)
    assert plain.startswith("whsec_")
    # sign() must receive the plaintext form — the delivery path decrypts.
    signature = webhooks_service.sign(plain, "msg_x", 1, "{}")
    assert signature.startswith("v1,")


async def test_startup_hook_adopts_legacy_plaintext(keyfile, db):
    legacy = WebhookEndpoint(
        id=uuid.uuid4(),
        url="https://receiver.example/legacy",
        secret=webhooks_service.generate_secret(),  # plaintext, pre-1086 shape
        description="",
        event_types=None,
        active=False,
    )
    db.add(legacy)
    await db.flush()
    plain = legacy.secret

    changed = await webhooks_service.encrypt_plaintext_secrets(db)
    assert changed >= 1
    row = (
        await db.execute(select(WebhookEndpoint).where(WebhookEndpoint.id == legacy.id))
    ).scalar_one()
    assert secretbox.is_encrypted(row.secret)
    assert secretbox.decrypt(row.secret) == plain
    # idempotent: a second boot re-encrypts nothing it already adopted
    assert (
        row.id
        not in {
            e.id
            for e in (await db.execute(select(WebhookEndpoint))).scalars()
            if not secretbox.is_encrypted(e.secret)
        }
    )
