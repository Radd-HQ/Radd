"""RADD-1446 — the remaining replayed secrets are ciphertext at rest.

RADD-1424 sealed the importer credentials, the SSO client secret and the LDAP
bind password (`test_secrets_at_rest.py`); this is the rest of the inventory:
the AI provider's `api_key`, a storage host's `access_key`/`secret_key`, the
code-host connections' `api_token`/`webhook_secret` (Forgejo, GitHub, GitLab),
a mail source's and sender's `secret`, an Alertmanager receiver's `token` and
the TOTP seed. For each, the RAW column must not hold the plaintext and the
consumer must still get the working value: the AI client sends the key, the S3
client is built with the credentials, each webhook verifies against the
decrypted secret, the IMAP login and the SMTP send carry the password, the
Alertmanager receiver authenticates, the TOTP code verifies. A row stored before
this change reads as-is and takes its encrypted form at boot; a boot without a
usable key logs and leaves it alone.

DB-backed tests are flushed, never committed, except the startup sweeps, which
open their own session and clean up after themselves.
"""

import hashlib
import hmac
import importlib
import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from radd import secretbox, smtp
from radd.config import settings
from radd.db import SessionLocal, get_session
from radd.exceptions import ConflictError, ForbiddenError
from radd.modules.ai import client as ai_client
from radd.modules.ai import registry as ai_registry
from radd.modules.ai.models import AiProviderRow
from radd.modules.ai.schemas import AiProviderCreate, AiRoleAssign
from radd.modules.ai.types import AiRole, AiWireShape
from radd.modules.alertmanager import service as alert_service
from radd.modules.alertmanager.models import AlertReceiver
from radd.modules.alertmanager.router import router as alertmanager_router
from radd.modules.alertmanager.schemas import ReceiverCreate, ReceiverUpdate
from radd.modules.attachments import clients as storage_clients
from radd.modules.attachments import hosts
from radd.modules.attachments.models import StorageHost
from radd.modules.attachments.schemas import StorageHostCreate, StorageHostRead, StorageHostUpdate
from radd.modules.attachments.types import StorageHostType
from radd.modules.auth import router as auth_router
from radd.modules.auth import service as auth_service
from radd.modules.auth import totp
from radd.modules.auth.models import User, UserTotp
from radd.modules.auth.schemas import UserCreate
from radd.modules.auth.types import InstanceRole
from radd.modules.forgejo.models import ForgejoConnection
from radd.modules.github.models import GithubConnection
from radd.modules.gitlab.models import GitlabConnection
from radd.modules.mailintake import poller
from radd.modules.mailintake import registry as mail_registry
from radd.modules.mailintake.config_schemas import MailSenderWrite, MailSourceWrite
from radd.modules.mailintake.models import MailSender, MailSource
from radd.modules.mailintake.providers import OutboundMessage
from radd.modules.mailintake.senders.smtp_sender import SmtpSender
from radd.modules.mailintake.sources import webhook as mail_webhook
from radd.modules.mailintake.types import MailSenderKind, MailSourceKind
from radd.modules.vcs.connector_kit.schemas import ConnectionCreate

PASSWORD = "secrets-at-rest-pass-1"
# By module path: the package's `config_router` attribute is the APIRouter.
mail_config = importlib.import_module("radd.modules.mailintake.config_router")


async def _raw(db, table: str, column: str, row_id, key: str = "id") -> str:
    return await db.scalar(text(f"SELECT {column} FROM {table} WHERE {key} = :id"), {"id": row_id})


def _sealed(stored: str, plain: str) -> bool:
    return secretbox.is_encrypted(stored) and plain not in stored and secretbox.decrypt(stored) == plain


# --- AI provider ----------------------------------------------------------------


async def test_ai_api_key_is_ciphertext_and_the_client_sends_it(db):
    provider = await ai_registry.create_provider(
        db,
        AiProviderCreate(
            name=f"ai-{uuid.uuid4().hex[:8]}", wire_shape=AiWireShape.OPENAI,
            base_url="http://vllm.local:8000/v1", api_key="ai-key-plain", default_model="m",
        ),
    )
    await db.flush()
    assert _sealed(await _raw(db, "ai_providers", "api_key", provider.id), "ai-key-plain")
    assert provider.has_api_key is True

    await ai_registry.set_role(db, AiRole.CHAT, AiRoleAssign(provider_id=provider.id))
    sent: dict[str, str] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        sent.update(request.headers)
        return httpx.Response(200, json={"choices": [{"message": {"content": "pong"}}]})

    ai_client.transport = httpx.MockTransport(handle)
    try:
        assert await ai_client.complete(db, AiRole.CHAT, "system", "hello") == "pong"
    finally:
        ai_client.transport = None
    assert sent["authorization"] == "Bearer ai-key-plain"


# --- storage host ---------------------------------------------------------------


def _s3(**overrides) -> StorageHostCreate:
    payload: dict[str, Any] = {
        "name": f"s3-{uuid.uuid4().hex[:8]}", "host_type": StorageHostType.S3,
        "endpoint": "garage:3900", "access_key": "AK-plain", "secret_key": "SK-plain", "bucket": "b",
    }
    payload.update(overrides)
    return StorageHostCreate(**payload)


async def test_storage_host_credentials_are_ciphertext_and_the_s3_client_gets_them(db, monkeypatch):
    host = await hosts.create_host(db, _s3())
    await db.flush()
    assert _sealed(await _raw(db, "storage_hosts", "access_key", host.id), "AK-plain")
    assert _sealed(await _raw(db, "storage_hosts", "secret_key", host.id), "SK-plain")
    assert host.has_access_key and host.has_secret_key

    built: dict[str, Any] = {}

    class FakeMinio:
        def __init__(self, endpoint: str, **kwargs: Any) -> None:
            built.update(endpoint=endpoint, **kwargs)

    monkeypatch.setattr("minio.Minio", FakeMinio)
    storage_clients.S3Client(host)
    assert built["access_key"] == "AK-plain" and built["secret_key"] == "SK-plain"

    # Both credentials are write-only: the admin read says whether one is set.
    read = StorageHostRead.model_validate(host)
    assert read.has_access_key is True and "access_key" not in read.model_dump()
    assert "AK-plain" not in read.model_dump_json() and "SK-plain" not in read.model_dump_json()


async def test_a_blank_access_key_on_update_keeps_the_stored_one(db):
    host = await hosts.create_host(db, _s3())
    await hosts.update_host(db, host.id, StorageHostUpdate(access_key="", secret_key="", bucket="c"))
    assert secretbox.decrypt(host.access_key) == "AK-plain"
    assert secretbox.decrypt(host.secret_key) == "SK-plain"
    await hosts.update_host(db, host.id, StorageHostUpdate(access_key="AK-next"))
    assert secretbox.decrypt(host.access_key) == "AK-next"


# --- code-host connections (one kit, three hosts) -------------------------------


@dataclass(frozen=True)
class CodeHost:
    name: str
    table: str
    token_header: str
    token_prefix: str

    @property
    def store(self):
        return importlib.import_module(f"radd.modules.{self.name}.service").store

    def payload(self) -> tuple[dict, bytes]:
        """A push naming no repository, so resolution rests on the secret alone."""
        payload = {"ref": "refs/heads/main", "commits": []}
        return payload, json.dumps(payload).encode()

    def credential(self, body: bytes, secret: str) -> str:
        """What the receiver hands `authenticate`: a signature, or GitLab's echoed token."""
        if self.name == "gitlab":
            return secret
        digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return f"sha256={digest}" if self.name == "github" else digest


CODE_HOSTS = [
    CodeHost("forgejo", "forgejo_connections", "Authorization", "token "),
    CodeHost("github", "github_connections", "Authorization", "Bearer "),
    CodeHost("gitlab", "gitlab_connections", "PRIVATE-TOKEN", ""),
]


@pytest.mark.parametrize("host", CODE_HOSTS, ids=lambda h: h.name)
async def test_connection_credentials_are_ciphertext_and_the_webhook_and_api_still_use_them(db, host):
    connection = await host.store.create_connection(
        db,
        ConnectionCreate(
            name=f"{host.name}-{uuid.uuid4().hex[:6]}", base_url="https://h.example.com",
            api_token="tok-plain", webhook_secret="hook-plain",
        ),
    )
    await db.flush()
    assert _sealed(await _raw(db, host.table, "api_token", connection.id), "tok-plain")
    assert _sealed(await _raw(db, host.table, "webhook_secret", connection.id), "hook-plain")

    assert connection.api_headers[host.token_header] == f"{host.token_prefix}tok-plain"

    payload, body = host.payload()
    resolved = await host.store.resolve_for_payload(db, payload, body, host.credential(body, "hook-plain"))
    assert resolved is not None and resolved[0].id == connection.id
    assert await host.store.resolve_for_payload(db, payload, body, host.credential(body, "hook-wrong")) is None

    # Two active hosts may not share a secret — decided on the decrypted values,
    # since two ciphertexts of one secret never compare equal in SQL.
    with pytest.raises(ConflictError):
        await host.store.create_connection(
            db,
            ConnectionCreate(
                name=f"{host.name}-dup-{uuid.uuid4().hex[:6]}", base_url="https://dup.example.com",
                webhook_secret="hook-plain",
            ),
        )


# --- mail source and sender -----------------------------------------------------


async def test_mail_source_secret_is_ciphertext_and_the_ingest_route_verifies_the_plaintext(
    db, admin, monkeypatch
):
    address = f"help-{uuid.uuid4().hex[:6]}@example.test"
    source = await mail_config.create_source(
        MailSourceWrite(name=f"hook-{uuid.uuid4().hex[:6]}", kind=MailSourceKind.WEBHOOK,
                        address=address, secret="ingest-plain"),
        db, admin,
    )
    await db.flush()
    assert _sealed(await _raw(db, "mail_sources", "secret", source.id), "ingest-plain")
    assert source.has_secret is True

    # The route hands the DECRYPTED secret to the constant-time verifier. Spied
    # rather than replayed: a verified delivery would go on to commit the session.
    handed: list[str] = []

    def spy(raw_body: bytes, signature: str, secret: str) -> bool:
        handed.append(secret)
        return False

    monkeypatch.setattr(mail_webhook, "verify_signature", spy)
    from radd.app import create_app

    app = create_app()

    async def session_override():
        yield db

    app.dependency_overrides[get_session] = session_override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/integrations/email", content=b"raw",
            headers={"X-Radd-Signature": "sha256=00", "X-Radd-Envelope-To": address},
        )
    assert response.status_code == 401
    assert handed == ["ingest-plain"]


async def test_imap_source_secret_is_ciphertext_and_the_poller_logs_in_with_it(db, admin, monkeypatch):
    created = await mail_config.create_source(
        MailSourceWrite(name=f"imap-{uuid.uuid4().hex[:6]}", kind=MailSourceKind.IMAP,
                        address="inbox@example.test", host="imap.example.test", port=993,
                        username="inbox", secret="mailbox-plain"),
        db, admin,
    )
    await db.flush()
    assert _sealed(await _raw(db, "mail_sources", "secret", created.id), "mailbox-plain")
    source = await mail_registry.get_source(db, created.id)  # the poller works from the row

    logins: list[tuple[str, str]] = []

    class FakeImap:
        def __init__(self, host: str, port: int) -> None:
            self.host, self.port = host, port

        def login(self, user: str, password: str) -> None:
            logins.append((user, password))

        def select(self, folder: str) -> None:
            pass

    monkeypatch.setattr(poller.imaplib, "IMAP4_SSL", FakeImap)
    poller._connect(source)
    assert logins == [("inbox", "mailbox-plain")]


async def test_mail_sender_secret_is_ciphertext_and_the_smtp_send_carries_it(db, admin, monkeypatch):
    created = await mail_config.create_sender(
        MailSenderWrite(name=f"smtp-{uuid.uuid4().hex[:6]}", kind=MailSenderKind.SMTP,
                        from_address="radd@example.test", host="smtp.example.test", port=587,
                        username="radd", secret="relay-plain"),
        db, admin,
    )
    await db.flush()
    assert _sealed(await _raw(db, "mail_senders", "secret", created.id), "relay-plain")
    sender = await mail_registry.get_sender(db, created.id)  # the sender works from the row

    configs: list[smtp.SmtpConfig] = []

    def fake_send(to_address, subject, body, *, config, **kwargs) -> str:
        configs.append(config)
        return "<sent@example.test>"

    monkeypatch.setattr(smtp, "send_message", fake_send)
    sent = await SmtpSender(sender).send(OutboundMessage(to_address="jane@example.test", subject="s", body="b"))
    assert sent == "<sent@example.test>"
    assert [c.password for c in configs] == ["relay-plain"]


# --- Alertmanager receiver ------------------------------------------------------


def _alert_app(db) -> FastAPI:
    app = FastAPI()
    app.include_router(alertmanager_router)

    async def _session():
        yield db

    app.dependency_overrides[get_session] = _session

    @app.exception_handler(ForbiddenError)
    async def _forbidden(_request, exc):
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    return app


async def test_alertmanager_token_is_ciphertext_and_the_receiver_still_authenticates(db):
    token = uuid.uuid4().hex
    receiver = await alert_service.create_receiver(
        db, ReceiverCreate(name=f"recv-{uuid.uuid4().hex[:6]}", token=token)
    )
    await db.flush()
    assert _sealed(await _raw(db, "alertmanager_receivers", "token", receiver.id), token)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_alert_app(db)), base_url="http://t") as client:
        accepted = await client.post(f"/integrations/alertmanager?token={token}", json={"alerts": []})
        refused = await client.post("/integrations/alertmanager?token=nope", json={"alerts": []})
    assert accepted.status_code == 200 and accepted.json() == {"created": 0, "triggered": 0}
    assert refused.status_code == 403

    # `KEEP_SECRET` keeps the stored token; a typed one replaces it, sealed.
    await alert_service.update_receiver(db, receiver.id, ReceiverUpdate(token=secretbox.KEEP_SECRET, label="x"))
    assert secretbox.decrypt(receiver.token) == token
    await alert_service.update_receiver(db, receiver.id, ReceiverUpdate(token="rotated-token"))
    assert _sealed(receiver.token, "rotated-token")


# --- TOTP seed ------------------------------------------------------------------


async def test_totp_seed_is_ciphertext_and_enrolment_confirm_and_login_verify_codes(db):
    user = await auth_service.create_user(
        db, UserCreate(email=f"totp-{uuid.uuid4().hex[:8]}@example.com", name="TOTP Probe", password=PASSWORD)
    )
    setup = await auth_router.totp_setup(user, db)  # the one-time display decrypts
    row = await auth_service.totp_row(db, user.id)
    stored = await _raw(db, "user_totp", "secret", user.id, key="user_id")
    assert _sealed(stored, setup.secret) and setup.secret in setup.otpauth_uri
    assert auth_service.totp_secret(row) == setup.secret

    now = int(time.time())
    codes = await auth_service.totp_confirm(db, user, totp.code_at(setup.secret, now))
    assert len(codes) == totp.RECOVERY_CODE_COUNT
    signed_in = await auth_service.authenticate_with_totp(db, user.email, PASSWORD, totp.code_at(setup.secret, now))
    assert signed_in.id == user.id


# --- the startup sweeps: a deploy does not wait for someone to press Save -----


@pytest.fixture
async def committed_legacy_rows():
    """One legacy plaintext row per sweep — written through the ORM, which is
    what every pre-RADD-1446 save amounted to — committed, and removed after."""
    tag = uuid.uuid4().hex[:8]
    user = User(email=f"sweep-{tag}@example.com", name="Sweep", instance_role=InstanceRole.MEMBER.value)
    rows: list[Any] = [
        AiProviderRow(name=f"sweep-{tag}", wire_shape=AiWireShape.OPENAI.value, api_key="ai-legacy"),
        StorageHost(name=f"sweep-{tag}", host_type=StorageHostType.S3.value, endpoint="garage:3900",
                    access_key="ak-legacy", secret_key="sk-legacy", bucket="b"),
        ForgejoConnection(name=f"sweep-{tag}", base_url="https://fj.example.com",
                          api_token="fj-token-legacy", webhook_secret="fj-hook-legacy", active=False),
        GithubConnection(name=f"sweep-{tag}", base_url="https://gh.example.com",
                         api_token="gh-token-legacy", webhook_secret="gh-hook-legacy", active=False),
        GitlabConnection(name=f"sweep-{tag}", base_url="https://gl.example.com",
                         api_token="gl-token-legacy", webhook_secret="gl-hook-legacy", active=False),
        MailSource(name=f"sweep-{tag}", kind=MailSourceKind.WEBHOOK.value, address=f"sweep-{tag}@example.test",
                   secret="source-legacy", enabled=False),
        MailSender(name=f"sweep-{tag}", kind=MailSenderKind.SMTP.value, from_address="r@example.test",
                   host="smtp.example.test", secret="sender-legacy", enabled=False),
        AlertReceiver(name=f"sweep-{tag}", token="alert-legacy", active=False),
    ]
    async with SessionLocal() as session:
        session.add(user)
        await session.flush()
        session.add_all([*rows, UserTotp(user_id=user.id, secret="TOTPLEGACYBASE32SEED")])
        await session.commit()
    expected = {
        ("ai_providers", "api_key", rows[0].id): "ai-legacy",
        ("storage_hosts", "access_key", rows[1].id): "ak-legacy",
        ("storage_hosts", "secret_key", rows[1].id): "sk-legacy",
        ("forgejo_connections", "api_token", rows[2].id): "fj-token-legacy",
        ("forgejo_connections", "webhook_secret", rows[2].id): "fj-hook-legacy",
        ("github_connections", "api_token", rows[3].id): "gh-token-legacy",
        ("github_connections", "webhook_secret", rows[3].id): "gh-hook-legacy",
        ("gitlab_connections", "api_token", rows[4].id): "gl-token-legacy",
        ("gitlab_connections", "webhook_secret", rows[4].id): "gl-hook-legacy",
        ("mail_sources", "secret", rows[5].id): "source-legacy",
        ("mail_senders", "secret", rows[6].id): "sender-legacy",
        ("alertmanager_receivers", "token", rows[7].id): "alert-legacy",
        ("user_totp", "secret", user.id): "TOTPLEGACYBASE32SEED",
    }
    yield expected
    async with SessionLocal() as session:
        for row in rows:
            await session.delete(await session.get(type(row), row.id))
        await session.delete(await session.get(User, user.id))  # cascades user_totp
        await session.commit()


async def _run_every_sweep() -> None:
    await ai_registry.encrypt_plaintext_secrets()
    await hosts.encrypt_plaintext_credentials()
    for host in CODE_HOSTS:
        await host.store.encrypt_plaintext_credentials()
    await mail_registry.encrypt_plaintext_secrets()
    await alert_service.encrypt_plaintext_tokens()
    await auth_service.encrypt_plaintext_totp_secrets()


async def _stored(expected: dict) -> dict:
    async with SessionLocal() as session:
        return {
            key: await _raw(session, table, column, row_id, key="user_id" if table == "user_totp" else "id")
            for key in expected
            for table, column, row_id in [key]
        }


async def test_the_startup_sweeps_encrypt_every_legacy_secret(committed_legacy_rows):
    await _run_every_sweep()
    for key, stored in (await _stored(committed_legacy_rows)).items():
        assert _sealed(stored, committed_legacy_rows[key]), key


@pytest.fixture
def unusable_key(tmp_path, monkeypatch):
    """A backup key file that is not base64: `secretbox` cannot derive a key from it."""
    key_path = tmp_path / "key"
    key_path.write_bytes(b"!!not-base64!!")
    monkeypatch.setattr(settings, "backup_key_file", str(key_path))
    secretbox.reset_key_cache()
    yield
    secretbox.reset_key_cache()


async def test_a_boot_without_a_usable_key_logs_and_leaves_legacy_secrets_alone(
    committed_legacy_rows, unusable_key, caplog
):
    caplog.set_level(logging.WARNING)
    await _run_every_sweep()  # never raises — boot does not wait on the key
    for key, stored in (await _stored(committed_legacy_rows)).items():
        assert stored == committed_legacy_rows[key], key
    owners = ("ai:", "attachments:", "forgejo:", "github:", "gitlab:", "mailintake:", "alertmanager:", "auth:")
    warnings = [r.getMessage() for r in caplog.records if "stay plaintext this boot" in r.getMessage()]
    assert all(any(w.startswith(owner) for w in warnings) for owner in owners), warnings
