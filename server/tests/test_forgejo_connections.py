"""Spec 111: connections as rows, and which host is trusted to have signed a payload.

The interesting invariant is negative. With one env secret there was one answer;
with rows, a payload from a KNOWN repository must be verified against that
repository's own connection and nothing else — otherwise a second host's secret
would authorise writes against the first host's repositories.

Runs against live Postgres inside a transaction that is rolled back, like the
reporting and SLQ tests.
"""

import hashlib
import hmac
import json
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings
from radd.modules.forgejo import service
from radd.modules.forgejo.models import ForgejoConnection, ForgejoRepo
from radd.modules.forgejo.schemas import ConnectionCreate, ConnectionUpdate, RepoCreate, RepoUpdate
from radd.exceptions import ConflictError
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate


@pytest.fixture
async def db():
    engine = create_async_engine(settings.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _payload(full_name: str = "") -> tuple[dict, bytes]:
    payload = {"ref": "refs/heads/main", "repository": {"full_name": full_name} if full_name else {}}
    return payload, json.dumps(payload).encode()


async def _connection(db, name: str, secret: str, *, active: bool = True) -> ForgejoConnection:
    connection = await service.create_connection(
        db, ConnectionCreate(name=name, base_url=f"https://{name}.example.com", webhook_secret=secret)
    )
    if not active:
        connection.active = False
        await db.flush()
    return connection


# --- resolution ---


async def test_known_repo_is_verified_against_its_own_connection(db):
    first = await _connection(db, f"first-{uuid.uuid4().hex[:6]}", "secret-one")
    second = await _connection(db, f"second-{uuid.uuid4().hex[:6]}", "secret-two")
    await service.create_repo(db, RepoCreate(connection_id=first.id, full_name="acme/widgets"))

    payload, body = _payload("acme/widgets")

    resolved = await service.resolve_for_payload(db, payload, body, _sign(body, "secret-one"))
    assert resolved is not None and resolved[0].id == first.id
    assert resolved[1] is not None and resolved[1].full_name == "acme/widgets"

    # The OTHER host's secret must not authorise a write against this repository,
    # even though that connection is active and its secret is genuine.
    assert await service.resolve_for_payload(db, payload, body, _sign(body, "secret-two")) is None
    assert second.active is True  # ...and not because the second host was ignored


async def test_unknown_repo_falls_back_to_any_active_connection(db):
    await _connection(db, f"host-{uuid.uuid4().hex[:6]}", "secret-one")
    payload, body = _payload("nobody/knows-this")

    resolved = await service.resolve_for_payload(db, payload, body, _sign(body, "secret-one"))
    assert resolved is not None and resolved[1] is None  # verified, but no repo row
    assert await service.resolve_for_payload(db, payload, body, _sign(body, "nope")) is None


async def test_inactive_connection_signs_nothing(db):
    connection = await _connection(db, f"off-{uuid.uuid4().hex[:6]}", "secret-one", active=False)
    await service.create_repo(db, RepoCreate(connection_id=connection.id, full_name="acme/off"))

    for full_name in ("acme/off", "someone/else"):
        payload, body = _payload(full_name)
        assert await service.resolve_for_payload(db, payload, body, _sign(body, "secret-one")) is None


async def test_repo_lookup_is_case_insensitive(db):
    connection = await _connection(db, f"case-{uuid.uuid4().hex[:6]}", "secret-one")
    await service.create_repo(db, RepoCreate(connection_id=connection.id, full_name="Acme/Widgets"))

    payload, body = _payload("acme/widgets")  # Forgejo is not case-sensitive about these
    resolved = await service.resolve_for_payload(db, payload, body, _sign(body, "secret-one"))
    assert resolved is not None and resolved[1] is not None


async def test_missing_signature_never_resolves(db):
    await _connection(db, f"nosig-{uuid.uuid4().hex[:6]}", "secret-one")
    payload, body = _payload()
    assert await service.resolve_for_payload(db, payload, body, "") is None


# --- the mapping is a default, not a filter ---


async def test_project_mapping_does_not_gate_resolution(db):
    """A repository mapped to no project still resolves: keys are unique
    instance-wide, so making the map authoritative would silently drop links
    from a shared repository."""
    connection = await _connection(db, f"map-{uuid.uuid4().hex[:6]}", "secret-one")
    repo = await service.create_repo(
        db, RepoCreate(connection_id=connection.id, full_name="acme/unmapped")
    )
    assert repo.project_id is None

    payload, body = _payload("acme/unmapped")
    resolved = await service.resolve_for_payload(db, payload, body, _sign(body, "secret-one"))
    assert resolved is not None and resolved[1].id == repo.id


async def test_repo_update_clears_the_mapping_with_an_explicit_null(db):
    connection = await _connection(db, f"clear-{uuid.uuid4().hex[:6]}", "secret-one")
    project = await projects_service.create_project(
        db, ProjectCreate(key=f"FG{uuid.uuid4().hex[:4].upper()}", name="Forgejo mapping")
    )
    repo = await service.create_repo(
        db,
        RepoCreate(
            connection_id=connection.id, full_name="acme/clearable", project_id=project.id
        ),
    )

    # omitted = unchanged
    await service.update_repo(db, repo.id, RepoUpdate(default_branch="trunk"))
    assert repo.project_id is not None and repo.default_branch == "trunk"
    # explicit null = cleared
    await service.update_repo(db, repo.id, RepoUpdate(project_id=None))
    assert repo.project_id is None


# --- credentials ---


async def test_empty_credential_on_update_keeps_the_stored_one(db):
    connection = await _connection(db, f"cred-{uuid.uuid4().hex[:6]}", "secret-one")
    connection.api_token = "token-abc"
    await db.flush()

    await service.update_connection(db, connection.id, ConnectionUpdate(name="renamed"))
    assert connection.webhook_secret == "secret-one" and connection.api_token == "token-abc"

    await service.update_connection(db, connection.id, ConnectionUpdate(webhook_secret=""))
    assert connection.webhook_secret == "secret-one"  # a round-tripped blank must not wipe it

    await service.update_connection(db, connection.id, ConnectionUpdate(webhook_secret="rotated"))
    assert connection.webhook_secret == "rotated"


async def test_duplicate_names_and_repos_conflict(db):
    name = f"dupe-{uuid.uuid4().hex[:6]}"
    connection = await _connection(db, name, "secret-one")
    with pytest.raises(ConflictError):
        await service.create_connection(
            db, ConnectionCreate(name=name, base_url="https://elsewhere.example.com")
        )
    await service.create_repo(db, RepoCreate(connection_id=connection.id, full_name="acme/dup"))
    with pytest.raises(ConflictError):
        await service.create_repo(
            db, RepoCreate(connection_id=connection.id, full_name="ACME/DUP")
        )
