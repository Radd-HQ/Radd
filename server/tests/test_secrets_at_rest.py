"""RADD-1424 — importer, SSO and LDAP secrets are ciphertext at rest.

The webhook precedent (RADD-1086, `test_secretbox.py`) applied to the four
remaining replayed secrets: the Jira and Confluence connection credential, the
SSO provider's client secret and the `ldap_bind_password` setting. For each,
the RAW column must not hold the plaintext and the read path that replays it
must still hand the working value to its client. A row stored before this
change reads as-is and takes its encrypted form on the next save (or boot).

DB-backed tests are flushed, never committed, except the startup sweeps, which
open their own session and clean up after themselves.
"""

import uuid

import httpx
import pytest
from sqlalchemy import text

from radd import secretbox
from radd.db import SessionLocal
from radd.modules.confluenceimport import connections as confluence_connections
from radd.modules.confluenceimport.client import ConfluenceClient
from radd.modules.confluenceimport.models import ConfluenceConnection
from radd.modules.confluenceimport.schemas import ConnectionCreate
from radd.modules.events import service as events
from radd.modules.jiraimport import connections as jira_connections
from radd.modules.jiraimport.client import JiraClient
from radd.modules.jiraimport.models import JiraConnection
from radd.modules.jiraimport.schemas import JiraConnectionCreate, JiraConnectionUpdate
from radd.modules.jiraimport.types import JiraAuthMode, JiraEvent
from radd.modules.ldap import service as ldap_service
from radd.modules.settings import service as settings_service
from radd.modules.settings.models import ScopedSetting
from radd.modules.settings.types import SettingEvent, SettingKey, SettingScope, setting_spec
from radd.modules.sso import idp
from radd.modules.sso import registry as sso_registry
from radd.modules.sso.models import SsoProvider
from radd.modules.sso.schemas import SsoProviderCreate, SsoProviderUpdate
from radd.modules.sso.types import SsoKind


async def _raw(db, table: str, column: str, row_id) -> str:
    return await db.scalar(text(f"SELECT {column} FROM {table} WHERE id = :id"), {"id": row_id})


async def _raw_setting(db, key: SettingKey):
    return await db.scalar(
        text("SELECT value FROM scoped_settings WHERE key = :key AND scope = 'instance'"),
        {"key": key.value},
    )


def _jira(**overrides) -> JiraConnectionCreate:
    payload = {
        "name": f"jira-{uuid.uuid4().hex[:8]}",
        "base_url": "https://jira.example.com",
        "auth_mode": JiraAuthMode.PAT,
        "credential": "jira-pat-plain",
    }
    payload.update(overrides)
    return JiraConnectionCreate(**payload)


# --- each secret: ciphertext in the column, plaintext on the replay path ------


async def test_jira_credential_is_ciphertext_and_the_client_replays_it(db):
    connection = await jira_connections.create_connection(db, _jira())
    await db.flush()

    stored = await _raw(db, "jira_connections", "credential", connection.id)
    assert secretbox.is_encrypted(stored) and "jira-pat-plain" not in stored
    assert connection.has_credential is True

    with JiraClient(jira_connections.creds_of(connection)) as jira:
        assert jira._http.headers["Authorization"] == "Bearer jira-pat-plain"


async def test_confluence_credential_is_ciphertext_and_the_client_replays_it(db):
    connection = await confluence_connections.create_connection(
        db,
        ConnectionCreate(
            name=f"wiki-{uuid.uuid4().hex[:8]}",
            base_url="https://wiki.example.com",
            credential="confluence-pat-plain",
        ),
    )
    await db.flush()

    stored = await _raw(db, "confluence_connections", "credential", connection.id)
    assert secretbox.is_encrypted(stored) and "confluence-pat-plain" not in stored

    client = ConfluenceClient(confluence_connections.creds_of(connection))
    try:
        assert client.http.headers["Authorization"] == "Bearer confluence-pat-plain"
    finally:
        client.close()


async def test_an_empty_confluence_credential_stays_empty(db):
    """`has_credential` reads the column's truthiness; an encrypted "" would lie."""
    connection = await confluence_connections.create_connection(
        db, ConnectionCreate(name=f"wiki-{uuid.uuid4().hex[:8]}", base_url="https://wiki.example.com")
    )
    assert connection.credential == "" and connection.has_credential is False


async def test_sso_client_secret_is_ciphertext_and_the_token_exchange_sends_it(db):
    provider = await sso_registry.create_provider(
        db,
        SsoProviderCreate(
            kind=SsoKind.GITHUB, name=f"gh-{uuid.uuid4().hex[:6]}",
            client_id="client-id", client_secret="sso-secret-plain",
        ),
    )
    await db.flush()

    stored = await _raw(db, "sso_providers", "client_secret", provider.id)
    assert secretbox.is_encrypted(stored) and "sso-secret-plain" not in stored
    assert provider.has_client_secret and sso_registry.configured(provider)

    sent: dict[str, str] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        sent.update(httpx.QueryParams(request.content.decode()))
        return httpx.Response(200, json={"access_token": "t"})

    idp.transport = httpx.MockTransport(handle)
    try:
        await idp.exchange_tokens(provider, "code", {"verifier": "v"}, "https://radd.example/cb")
    finally:
        idp.transport = None
        idp.invalidate_caches(provider.id)
    assert sent["client_secret"] == "sso-secret-plain"


async def test_ldap_bind_password_is_ciphertext_and_the_service_bind_uses_it(db, monkeypatch):
    monkeypatch.setattr(ldap_service, "_conn", ldap_service._conn)  # restored after
    for key, value in (
        (SettingKey.LDAP_URL, "ldaps://ad.example.com"),
        (SettingKey.LDAP_USER_DOMAIN, "ad.example.com"),
        (SettingKey.LDAP_BIND_DN, "CN=svc-radd,DC=ad,DC=example,DC=com"),
        (SettingKey.LDAP_BIND_PASSWORD, "bind-password-plain"),
    ):
        await settings_service.set_value(db, key, SettingScope.INSTANCE, None, value)

    stored = await _raw_setting(db, SettingKey.LDAP_BIND_PASSWORD)
    assert secretbox.is_encrypted(stored) and "bind-password-plain" not in stored

    bound: dict[str, str] = {}
    monkeypatch.setattr(ldap_service.ldap3, "Server", lambda *a, **k: object())
    monkeypatch.setattr(
        ldap_service.ldap3, "Connection", lambda server, **kwargs: bound.update(kwargs)
    )
    await ldap_service.refresh_conn(db)
    ldap_service.service_connection()
    assert bound["password"] == "bind-password-plain"


# --- the audit trail and the member-readable resolve route --------------------


async def test_a_secret_setting_change_is_recorded_without_its_value(db, admin):
    await settings_service.set_value(
        db, SettingKey.LDAP_BIND_PASSWORD, SettingScope.INSTANCE, None, "first-plain",
        actor_id=admin.id,
    )
    await settings_service.set_value(
        db, SettingKey.LDAP_BIND_PASSWORD, SettingScope.INSTANCE, None, "second-plain",
        actor_id=admin.id,
    )
    await db.flush()
    rows = await events.query_events(
        db, event_types=[SettingEvent.CHANGED], entity_id=SettingKey.LDAP_BIND_PASSWORD.value,
        limit=5,
    )
    assert rows, "a secret change is still audited"
    for row in rows:
        assert row.payload["changes"] == [
            {"field": "ldap_bind_password", "name": "Bind account password"}
        ]
        assert "plain" not in str(row.payload)


async def test_the_resolve_route_never_hands_out_a_secret_setting(db):
    """`/scoped-settings/resolve` is readable by any member and by Anyone."""
    from radd.app import create_app
    from radd.db import get_session

    await settings_service.set_value(
        db, SettingKey.LDAP_BIND_PASSWORD, SettingScope.INSTANCE, None, "bind-password-plain"
    )
    await db.flush()

    async def session_override():
        yield db

    app = create_app()
    app.dependency_overrides[get_session] = session_override
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        refused = await client.get(
            "/api/v1/scoped-settings/resolve", params={"key": "ldap_bind_password"}
        )
        allowed = await client.get(
            "/api/v1/scoped-settings/resolve", params={"key": "ldap_url"}
        )
    assert refused.status_code == 403, refused.text
    assert "bind-password-plain" not in refused.text
    assert allowed.status_code == 200, allowed.text


async def test_the_settings_list_marks_a_secret_as_set_and_never_carries_it(db, admin):
    """RADD-1454: the admin-gated list (`GET /scoped-settings?scope=instance`, every
    Directory-page load) says WHETHER a secret is set; the plaintext never reaches the
    browser. A typed replacement round-trips, an empty write keeps the stored value,
    and DELETE is the one way to clear it."""
    from radd.app import create_app
    from radd.db import get_session
    from radd.modules.auth.deps import current_user

    key = SettingKey.LDAP_BIND_PASSWORD
    await settings_service.set_value(
        db, key, SettingScope.INSTANCE, None, "bind-password-plain", actor_id=admin.id
    )
    await db.flush()

    async def session_override():
        yield db

    app = create_app()
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[current_user] = lambda: admin
    path, scope = "/api/v1/scoped-settings", {"scope": SettingScope.INSTANCE.value}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        listed = await client.get(path, params=scope)
        assert listed.status_code == 200, listed.text
        assert "bind-password-plain" not in listed.text
        rows = {row["key"]: row for row in listed.json()}
        secret = rows[key.value]
        assert secret["secret"] is True and secret["set"] is True and secret["set_here"] is True
        assert secret["value"] is None and secret["default"] is None
        # A plain setting still carries its value; `set` is the secret's marker alone.
        assert rows[SettingKey.LDAP_URL.value]["set"] is None

        replaced = await client.put(path, json={**scope, "key": key.value, "value": "second-plain"})
        assert replaced.status_code == 200, replaced.text
        assert "second-plain" not in replaced.text and replaced.json()["set"] is True
        assert await settings_service.resolve(db, key) == "second-plain"

        kept = await client.put(path, json={**scope, "key": key.value, "value": ""})
        assert kept.status_code == 200, kept.text
        assert kept.json()["set"] is True
        assert await settings_service.resolve(db, key) == "second-plain"

        cleared = await client.delete(path, params={**scope, "key": key.value})
        assert cleared.status_code == 204, cleared.text
        after = next(r for r in (await client.get(path, params=scope)).json() if r["key"] == key.value)
        assert after["set_here"] is False and after["value"] is None
    assert await settings_service.resolve(db, key) == setting_spec(key).default


# --- rows stored before encryption landed -------------------------------------


async def test_a_legacy_plaintext_credential_reads_and_is_encrypted_on_save(db):
    connection = await jira_connections.create_connection(db, _jira())
    await db.execute(
        text("UPDATE jira_connections SET credential = 'legacy-plain' WHERE id = :id"),
        {"id": connection.id},
    )
    await db.refresh(connection)
    assert jira_connections.creds_of(connection).credential == "legacy-plain"

    await jira_connections.update_connection(
        db, connection.id, JiraConnectionUpdate(name=f"renamed-{uuid.uuid4().hex[:6]}")
    )
    await db.flush()

    stored = await _raw(db, "jira_connections", "credential", connection.id)
    assert secretbox.is_encrypted(stored) and "legacy-plain" not in stored
    assert jira_connections.creds_of(connection).credential == "legacy-plain"
    # Adoption is not an edit: the audit row names only the rename.
    [event] = await events.query_events(
        db, event_types=[JiraEvent.CONNECTION_UPDATED], entity_id=str(connection.id), limit=1
    )
    assert [c["field"] for c in event.payload["changes"]] == ["name"]


async def test_a_legacy_client_secret_is_encrypted_on_save(db):
    provider = await sso_registry.create_provider(
        db, SsoProviderCreate(kind=SsoKind.GITHUB, name=f"gh-{uuid.uuid4().hex[:6]}", client_id="c")
    )
    await db.execute(
        text("UPDATE sso_providers SET client_secret = 'legacy-plain' WHERE id = :id"),
        {"id": provider.id},
    )
    await db.refresh(provider)
    await sso_registry.update_provider(db, provider.id, SsoProviderUpdate(position=3))
    await db.flush()

    stored = await _raw(db, "sso_providers", "client_secret", provider.id)
    assert secretbox.is_encrypted(stored) and secretbox.decrypt(stored) == "legacy-plain"


async def test_a_legacy_plaintext_setting_reads_and_is_encrypted_on_save(db):
    await db.execute(
        text("DELETE FROM scoped_settings WHERE key = :key"),
        {"key": SettingKey.LDAP_BIND_PASSWORD.value},
    )
    db.add(
        ScopedSetting(
            scope=SettingScope.INSTANCE.value, scope_id=None,
            key=SettingKey.LDAP_BIND_PASSWORD.value, value="legacy-plain",
        )
    )
    await db.flush()
    resolved = await settings_service.resolve(db, SettingKey.LDAP_BIND_PASSWORD)
    assert resolved == "legacy-plain"

    # Restating the value is not a change (no audit row) but does rewrite it.
    await settings_service.set_value(
        db, SettingKey.LDAP_BIND_PASSWORD, SettingScope.INSTANCE, None, "legacy-plain"
    )
    await db.flush()
    stored = await _raw_setting(db, SettingKey.LDAP_BIND_PASSWORD)
    assert secretbox.is_encrypted(stored) and "legacy-plain" not in stored
    assert await settings_service.resolve(db, SettingKey.LDAP_BIND_PASSWORD) == "legacy-plain"
    assert not await events.query_events(
        db, event_types=[SettingEvent.CHANGED],
        entity_id=SettingKey.LDAP_BIND_PASSWORD.value, limit=1,
    )


# --- the startup sweeps: a deploy does not wait for someone to press Save -----


@pytest.fixture
async def committed_legacy_rows():
    """One legacy plaintext row per sweep — written through the ORM, which is
    what every pre-RADD-1424 save amounted to — committed, and removed after."""
    rows = [
        JiraConnection(
            name=f"sweep-{uuid.uuid4().hex[:8]}", base_url="https://jira.example.com",
            credential="jira-legacy",
        ),
        ConfluenceConnection(
            name=f"sweep-{uuid.uuid4().hex[:8]}", base_url="https://wiki.example.com",
            credential="wiki-legacy",
        ),
        SsoProvider(
            name=f"sweep-{uuid.uuid4().hex[:8]}", kind=SsoKind.GITHUB.value, enabled=False,
            client_id="c", client_secret="sso-legacy",
        ),
    ]
    setting_key = {"key": SettingKey.LDAP_BIND_PASSWORD.value}
    async with SessionLocal() as session:
        await session.execute(text("DELETE FROM scoped_settings WHERE key = :key"), setting_key)
        session.add_all(rows)
        session.add(
            ScopedSetting(
                scope=SettingScope.INSTANCE.value, scope_id=None,
                key=SettingKey.LDAP_BIND_PASSWORD.value, value="ldap-legacy",
            )
        )
        await session.commit()
    yield {type(row).__name__: row.id for row in rows}
    async with SessionLocal() as session:
        for row in rows:
            await session.delete(await session.get(type(row), row.id))
        await session.execute(text("DELETE FROM scoped_settings WHERE key = :key"), setting_key)
        await session.commit()


async def test_the_startup_sweeps_encrypt_every_legacy_secret(committed_legacy_rows):
    await jira_connections.encrypt_plaintext_credentials()
    await confluence_connections.encrypt_plaintext_credentials()
    await sso_registry.encrypt_plaintext_secrets()
    await settings_service.encrypt_plaintext_secrets()

    ids = committed_legacy_rows
    async with SessionLocal() as session:
        for table, column, row_id, plain in (
            ("jira_connections", "credential", ids["JiraConnection"], "jira-legacy"),
            ("confluence_connections", "credential", ids["ConfluenceConnection"], "wiki-legacy"),
            ("sso_providers", "client_secret", ids["SsoProvider"], "sso-legacy"),
        ):
            stored = await _raw(session, table, column, row_id)
            assert secretbox.is_encrypted(stored) and secretbox.decrypt(stored) == plain, table
        stored = await _raw_setting(session, SettingKey.LDAP_BIND_PASSWORD)
        assert secretbox.is_encrypted(stored) and secretbox.decrypt(stored) == "ldap-legacy"
