"""Jira connections (spec 100) — DB-managed instead of environment-only.

The invariants everything downstream leans on: exactly one default, a credential
that is never lost by a round-trip through the redacted read shape, and env
seeding that happens once and never resurrects a row the admin deleted.

CRUD tests are flushed, never committed; the session rolls back at teardown.
`seed_from_env` opens its OWN session and commits (it is a startup hook), so its
test cleans up explicitly.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.db import SessionLocal
from radd.exceptions import ConflictError
from radd.modules.jiraimport import connections
from radd.modules.jiraimport.models import JiraConnection
from radd.modules.jiraimport.schemas import JiraConnectionCreate, JiraConnectionUpdate
from radd.modules.jiraimport.types import JiraAuthMode, JiraConnectionSource


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


def _create(name: str = "", **overrides) -> JiraConnectionCreate:
    payload = {
        "name": name or f"jira-{uuid.uuid4().hex[:8]}",
        "base_url": "https://jira.example.com",
        "auth_mode": JiraAuthMode.PAT,
        "credential": "tok-1",
    }
    payload.update(overrides)
    return JiraConnectionCreate(**payload)


# --- the default invariant ----------------------------------------------------


async def test_the_first_connection_becomes_the_default(db):
    """A single-instance deploy must be complete the moment a connection is added,
    without the admin knowing the default flag exists."""
    await db.execute(text("DELETE FROM jira_connections"))
    connection = await connections.create_connection(db, _create())
    assert connection.is_default is True


async def test_exactly_one_connection_is_the_default(db):
    await db.execute(text("DELETE FROM jira_connections"))
    first = await connections.create_connection(db, _create("prod"))
    second = await connections.create_connection(db, _create("sandbox", is_default=True))

    await db.refresh(first)
    assert second.is_default is True
    assert first.is_default is False
    assert (await connections.default_connection(db)).id == second.id


async def test_a_lone_connection_is_the_default_even_unflagged(db):
    """Falling back to the only connection means an admin who never touched the
    flag — or who deleted the flagged row's siblings — still has a working deploy."""
    await db.execute(text("DELETE FROM jira_connections"))
    connection = JiraConnection(
        name=f"unflagged-{uuid.uuid4().hex[:6]}",
        base_url="https://jira.example.com",
        auth_mode=JiraAuthMode.PAT.value,
        credential="tok",
        is_default=False,
    )
    db.add(connection)
    await db.flush()
    assert (await connections.default_connection(db)).id == connection.id


async def test_deleting_the_default_promotes_another(db):
    await db.execute(text("DELETE FROM jira_connections"))
    first = await connections.create_connection(db, _create("prod"))
    await connections.create_connection(db, _create("sandbox"))
    await connections.delete_connection(db, first.id)

    promoted = await connections.default_connection(db)
    assert promoted is not None and promoted.name == "sandbox"
    assert promoted.is_default is True


async def test_require_connection_409s_when_none_exists(db):
    """409, not 404: the caller is allowed, the DEPLOY is missing a piece — the
    convention the ldap module set."""
    await db.execute(text("DELETE FROM jira_connections"))
    with pytest.raises(ConflictError):
        await connections.require_connection(db)


async def test_duplicate_names_are_rejected(db):
    await db.execute(text("DELETE FROM jira_connections"))
    await connections.create_connection(db, _create("prod"))
    with pytest.raises(ConflictError):
        await connections.create_connection(db, _create("prod"))


# --- credentials --------------------------------------------------------------


async def test_an_empty_credential_on_update_keeps_the_stored_one(db):
    """The read shape is redacted, so a form saving an untouched connection sends
    no credential back. That must not blank the token."""
    await db.execute(text("DELETE FROM jira_connections"))
    connection = await connections.create_connection(db, _create(credential="secret-token"))
    await connections.update_connection(
        db, connection.id, JiraConnectionUpdate(name="renamed", credential="")
    )
    assert connection.credential == "secret-token"
    assert connection.name == "renamed"


async def test_a_new_credential_on_update_replaces_it(db):
    await db.execute(text("DELETE FROM jira_connections"))
    connection = await connections.create_connection(db, _create(credential="old"))
    await connections.update_connection(db, connection.id, JiraConnectionUpdate(credential="new"))
    assert connection.credential == "new"


async def test_the_read_shape_exposes_only_whether_a_credential_is_stored(db):
    from radd.modules.jiraimport.schemas import JiraConnectionRead

    await db.execute(text("DELETE FROM jira_connections"))
    connection = await connections.create_connection(db, _create(credential="secret-token"))
    body = JiraConnectionRead.model_validate(connection).model_dump()
    assert body["has_credential"] is True
    assert "credential" not in body
    assert "secret-token" not in str(body)


async def test_basic_auth_requires_a_username():
    with pytest.raises(ValueError):
        _create(auth_mode=JiraAuthMode.BASIC, credential="pw")
    # ...and is accepted with one.
    assert _create(auth_mode=JiraAuthMode.BASIC, credential="pw", username="svc").username == "svc"


async def test_creds_of_carries_the_row_into_a_thread_safe_value(db):
    """REST calls run in worker threads, so what crosses that boundary must be a
    plain value — never the ORM row, whose lazy loads belong to another greenlet."""
    await db.execute(text("DELETE FROM jira_connections"))
    connection = await connections.create_connection(
        db, _create(base_url="https://jira.example.com/", verify_ssl=False)
    )
    creds = connections.creds_of(connection)
    assert creds.base_url == "https://jira.example.com"  # trailing slash stripped on save
    assert creds.auth_mode is JiraAuthMode.PAT
    assert creds.verify_ssl is False
    assert creds.usable is True


# --- env seeding --------------------------------------------------------------


async def _clear_connections() -> None:
    async with SessionLocal() as session:
        await session.execute(text("DELETE FROM jira_connections"))
        await session.commit()


@pytest.fixture
async def clean_connections():
    await _clear_connections()
    yield
    await _clear_connections()


async def test_env_seeding_creates_one_connection_from_a_spec_90_deploy(
    monkeypatch, clean_connections
):
    monkeypatch.setattr(settings, "jira_base_url", "https://jira.corp.example.com")
    monkeypatch.setattr(settings, "jira_pat", "env-token")
    monkeypatch.setattr(settings, "jira_user", "")
    monkeypatch.setattr(settings, "jira_password", "")

    await connections.seed_from_env()

    async with SessionLocal() as session:
        rows = await connections.list_connections(session)
    assert len(rows) == 1
    seeded = rows[0]
    assert seeded.base_url == "https://jira.corp.example.com"
    assert seeded.auth_mode == JiraAuthMode.PAT.value
    assert seeded.credential == "env-token"
    assert seeded.is_default is True
    assert seeded.source == JiraConnectionSource.ENV.value
    # Named after the host, so a deploy that has pointed at several instances over
    # time reads sensibly instead of showing a row called "default".
    assert seeded.name == "jira.corp.example.com"


async def test_env_seeding_prefers_a_pat_over_basic_credentials(
    monkeypatch, clean_connections
):
    monkeypatch.setattr(settings, "jira_base_url", "https://jira.corp.example.com")
    monkeypatch.setattr(settings, "jira_pat", "env-token")
    monkeypatch.setattr(settings, "jira_user", "svc")
    monkeypatch.setattr(settings, "jira_password", "pw")

    await connections.seed_from_env()

    async with SessionLocal() as session:
        seeded = (await connections.list_connections(session))[0]
    assert seeded.auth_mode == JiraAuthMode.PAT.value and seeded.username == ""


async def test_env_seeding_falls_back_to_basic_auth(monkeypatch, clean_connections):
    monkeypatch.setattr(settings, "jira_base_url", "https://jira.corp.example.com")
    monkeypatch.setattr(settings, "jira_pat", "")
    monkeypatch.setattr(settings, "jira_user", "svc")
    monkeypatch.setattr(settings, "jira_password", "pw")

    await connections.seed_from_env()

    async with SessionLocal() as session:
        seeded = (await connections.list_connections(session))[0]
    assert seeded.auth_mode == JiraAuthMode.BASIC.value
    assert seeded.username == "svc" and seeded.credential == "pw"


async def test_env_seeding_never_resurrects_a_deleted_connection(
    monkeypatch, clean_connections
):
    """Seeding runs on EVERY startup. It must not re-create a row the admin
    deleted, or re-add an instance they deliberately moved off."""
    monkeypatch.setattr(settings, "jira_base_url", "https://jira.corp.example.com")
    monkeypatch.setattr(settings, "jira_pat", "env-token")

    await connections.seed_from_env()
    async with SessionLocal() as session:
        seeded = (await connections.list_connections(session))[0]
        # The admin edits it — a seeded row is an ordinary editable connection.
        await connections.update_connection(
            session, seeded.id, JiraConnectionUpdate(base_url="https://jira.new.example.com")
        )
        await session.commit()

    await connections.seed_from_env()  # a second startup

    async with SessionLocal() as session:
        rows = await connections.list_connections(session)
    assert len(rows) == 1
    assert rows[0].base_url == "https://jira.new.example.com"  # the edit survived


async def test_env_seeding_is_a_no_op_without_an_env_configuration(
    monkeypatch, clean_connections
):
    monkeypatch.setattr(settings, "jira_base_url", "")
    monkeypatch.setattr(settings, "jira_pat", "")

    await connections.seed_from_env()

    async with SessionLocal() as session:
        assert await connections.list_connections(session) == []
