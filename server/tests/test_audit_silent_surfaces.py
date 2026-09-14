"""The silent admin surfaces emit (spec 123, RADD-1167).

Each of these writers produced NO event before this wave. The tests pin the
three properties an auditor depends on: the row exists and names the actor,
`changes` carries old → new, and a secret only ever appears as "changed".

DB-backed tests are flushed, never committed; the session rolls back at teardown.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.modules.ai import registry as ai_registry
from radd.modules.ai.schemas import AiProviderCreate, AiRoleAssign
from radd.modules.ai.types import AiEvent, AiRole, AiWireShape
from radd.modules.attachments import hosts
from radd.modules.attachments.schemas import StorageHostCreate, StorageHostUpdate
from radd.modules.attachments.types import AttachmentEvent, StorageHostType
from radd.modules.auth import public_access
from radd.modules.auth.models import User
from radd.modules.auth.types import AuthEvent, InstanceRole
from radd.modules.events import service as events
from radd.modules.projects import service as projects_service
from radd.modules.projects.schemas import ProjectCreate
from radd.modules.settings import service as settings_service
from radd.modules.settings.types import SettingEvent, SettingKey, SettingScope
from radd.modules.sso import registry as sso_registry
from radd.modules.sso.schemas import SsoProviderCreate, SsoProviderUpdate
from radd.modules.sso.types import SsoEvent, SsoKind
from radd.modules.timelogging import enablement
from radd.modules.timelogging.types import WorklogEvent


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def admin(db) -> User:
    user = User(
        email=f"audit-{uuid.uuid4().hex[:8]}@example.com",
        name="Audit Admin",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(user)
    await db.flush()
    return user


@pytest.fixture
async def project(db, admin):
    return await projects_service.create_project(
        db, ProjectCreate(key=f"AU{uuid.uuid4().hex[:4].upper()}", name="Audit"), actor_id=admin.id
    )


async def _latest(db, event_type: str, *, entity_id: str | None = None):
    await db.flush()
    rows = await events.query_events(db, event_types=[event_type], entity_id=entity_id, limit=1)
    return rows[0] if rows else None


def _change(event, field: str) -> dict:
    entry = next(c for c in event.payload["changes"] if c["field"] == field)
    return entry


# --- settings -------------------------------------------------------------------


async def test_setting_set_and_clear_emit_old_to_new(db, admin, project):
    key = SettingKey.ITEM_DEFAULT_VISIBILITY
    await settings_service.set_value(
        db, key, SettingScope.PROJECT, project.id, "restricted", actor_id=admin.id
    )
    event = await _latest(db, SettingEvent.CHANGED, entity_id=key.value)
    assert event is not None and event.actor_id == admin.id
    entry = _change(event, key.value)
    assert entry["to"] == "restricted" and "name" in entry
    assert event.payload["scope"] == "project"
    assert event.payload["project"]["key"] == project.key  # the subject ref

    await settings_service.clear_value(
        db, key, SettingScope.PROJECT, project.id, actor_id=admin.id
    )
    event = await _latest(db, SettingEvent.CHANGED, entity_id=key.value)
    assert _change(event, key.value) == {
        "field": key.value,
        "from": "restricted",
        "to": None,
        "name": _change(event, key.value)["name"],
    }


async def test_restating_a_setting_emits_nothing(db, admin, project):
    key = SettingKey.ITEM_DEFAULT_VISIBILITY
    await settings_service.set_value(
        db, key, SettingScope.PROJECT, project.id, "internal", actor_id=admin.id
    )
    first = await _latest(db, SettingEvent.CHANGED, entity_id=key.value)
    await settings_service.set_value(
        db, key, SettingScope.PROJECT, project.id, "internal", actor_id=admin.id
    )
    assert (await _latest(db, SettingEvent.CHANGED, entity_id=key.value)).id == first.id


# --- public access --------------------------------------------------------------


async def test_public_access_switch_is_its_own_audit_row(db, admin, project):
    await public_access.set_public_access(
        db, project, public=True, contributions=False, actor_id=admin.id
    )
    event = await _latest(db, AuthEvent.PROJECT_PUBLIC_ACCESS_CHANGED, entity_id=str(project.id))
    assert event is not None and event.actor_id == admin.id
    assert event.payload["changes"] == [{"field": "public", "from": False, "to": True}]
    assert event.payload["project"]["key"] == project.key


# --- secrets stay out of the trail ----------------------------------------------


async def test_sso_provider_secret_only_ever_reads_changed(db, admin):
    provider = await sso_registry.create_provider(
        db,
        SsoProviderCreate(
            kind=SsoKind.OIDC, name=f"idp-{uuid.uuid4().hex[:6]}", issuer="https://idp.example",
            client_id="a", client_secret="hunter2",
        ),
        actor_id=admin.id,
    )
    assert (await _latest(db, SsoEvent.PROVIDER_CREATED, entity_id=str(provider.id))) is not None
    await sso_registry.update_provider(
        db,
        provider.id,
        SsoProviderUpdate(client_secret="hunter3", client_id="b"),
        actor_id=admin.id,
    )
    event = await _latest(db, SsoEvent.PROVIDER_UPDATED, entity_id=str(provider.id))
    assert _change(event, "client_id") == {"field": "client_id", "from": "a", "to": "b"}
    assert _change(event, "client_secret") == {"field": "client_secret"}
    assert "hunter" not in str(event.payload)


async def test_storage_host_credentials_only_ever_read_changed(db, admin):
    host = await hosts.create_host(
        db,
        StorageHostCreate(
            name=f"s3-{uuid.uuid4().hex[:6]}", host_type=StorageHostType.S3,
            endpoint="http://garage:3900", access_key="AK", secret_key="SK", bucket="b",
            region="garage",
        ),
        actor_id=admin.id,
    )
    await hosts.update_host(
        db, host.id, StorageHostUpdate(secret_key="SK2", bucket="c"), actor_id=admin.id
    )
    event = await _latest(db, AttachmentEvent.HOST_UPDATED, entity_id=str(host.id))
    assert _change(event, "bucket") == {"field": "bucket", "from": "b", "to": "c"}
    assert _change(event, "secret_key") == {"field": "secret_key"}
    assert "SK" not in str(event.payload)


# --- names, not ids -------------------------------------------------------------


async def test_ai_role_change_names_the_providers(db, admin):
    first = await ai_registry.create_provider(
        db,
        AiProviderCreate(
            name=f"one-{uuid.uuid4().hex[:6]}", wire_shape=AiWireShape.OPENAI,
            base_url="http://a", default_model="m1",
        ),
        actor_id=admin.id,
    )
    second = await ai_registry.create_provider(
        db,
        AiProviderCreate(
            name=f"two-{uuid.uuid4().hex[:6]}", wire_shape=AiWireShape.OPENAI,
            base_url="http://b", default_model="m2",
        ),
        actor_id=admin.id,
    )
    await ai_registry.set_role(db, AiRole.CHAT, AiRoleAssign(provider_id=first.id), actor_id=admin.id)
    await ai_registry.set_role(
        db, AiRole.CHAT, AiRoleAssign(provider_id=second.id, model="m3"), actor_id=admin.id
    )
    event = await _latest(db, AiEvent.ROLE_CHANGED, entity_id=AiRole.CHAT.value)
    assert _change(event, "provider") == {"field": "provider", "from": first.name, "to": second.name}
    assert _change(event, "model") == {"field": "model", "from": None, "to": "m3"}


async def test_project_timelogging_switch_lands_in_the_project_history(db, admin, project):
    await enablement.set_enabled(db, project.id, True, actor_id=admin.id)
    event = await _latest(
        db, WorklogEvent.PROJECT_TIMELOGGING_CHANGED, entity_id=str(project.id)
    )
    assert event.payload["changes"] == [
        {"field": "timelogging_enabled", "from": False, "to": True}
    ]
    await enablement.set_enabled(db, project.id, True, actor_id=admin.id)
    assert (
        await _latest(db, WorklogEvent.PROJECT_TIMELOGGING_CHANGED, entity_id=str(project.id))
    ).id == event.id
