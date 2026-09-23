"""Directory settings page + automatic user sync (spec 85): the sync pass with
the directory stubbed at the service seam (the test_ad_depth idiom — ldap3
never touches the wire), cascade-resolved bases, and the sync-state rows.

DB-backed (compose Postgres) — flushed, never committed; the session rolls
back at teardown."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from radd.config import settings as config
from radd.modules.auth import service as auth_service
from radd.modules.auth.models import User, UserSession
from radd.modules.auth.schemas import UserCreate
from radd.modules.auth.types import InstanceRole, UserSource
from radd.modules.ldap import service as ldap_service, usersync
from radd.modules.ldap.models import DirectorySyncState
from radd.modules.ldap.router import directory_sync_status
from radd.modules.ldap.types import DirectoryUser, SyncKind
from radd.modules.settings import service as settings_service
from radd.modules.settings.types import SettingKey, SettingScope
from radd.modules.auth.types import LoginMethod


@pytest.fixture
async def db():
    engine = create_async_engine(config.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


def _directory_user(local: str, name: str | None = None) -> DirectoryUser:
    return DirectoryUser(
        username=local,
        email=f"{local}@dir85.example.com",
        name=name or local.title(),
        is_admin=False,
    )


def _stub_directory(monkeypatch, users: list[DirectoryUser], seen_bases: list[str] | None = None):
    """Replace the sync ldap3 enumeration at the service seam."""

    def fake_search(
        q: str = "", base: str | None = None, exclude_disabled: bool = True
    ) -> list[DirectoryUser]:
        if seen_bases is not None:
            seen_bases.append(base or "")
        return users

    monkeypatch.setattr(ldap_service, "search_directory_users", fake_search)


async def test_user_sync_provisions_and_updates_toggle_off(db, monkeypatch):
    """Toggle off (the default): provision + rename only — nobody deactivated.

    The toggle is cleared inside the test's own rolled-back transaction: the suite
    runs against a populated dev DB where a real deploy may have enabled the
    departure sweep at instance scope, and this test asserts the OFF behaviour.
    Without it, turning the feature on in the product fails its own test — and
    dangerously so, since the assertion that catches it is `deactivated == 0`."""
    await settings_service.clear_value(
        db, SettingKey.LDAP_USER_SYNC_DEACTIVATE_MISSING, SettingScope.INSTANCE, None
    )
    renamed = User(
        email="renamed@dir85.example.com",
        name="Old Name",
        password_hash=None,
        source=UserSource.LDAP,
    )
    missing = User(
        email="missing@dir85.example.com",
        name="Missing",
        password_hash=None,
        source=UserSource.LDAP,
    )
    db.add_all([renamed, missing])
    await db.flush()
    local = await auth_service.create_user(
        db,
        UserCreate(email="local@dir85.example.com", name="Local Person", password="password-123"),
    )

    directory = [
        _directory_user("newbie"),
        _directory_user("renamed", name="New Name"),
        # In the directory too, but a LOCAL account — never touched by the sync.
        _directory_user("local", name="Directory Name"),
    ]
    _stub_directory(monkeypatch, directory)

    result = await usersync.run_user_sync(db)
    assert result.provisioned == 1 and result.updated == 1 and result.deactivated == 0
    assert result.errors == []

    newbie = await auth_service.get_user_by_email(db, "newbie@dir85.example.com")
    assert newbie is not None
    assert newbie.password_hash is None and newbie.source == UserSource.LDAP
    assert newbie.active  # spec 86: a provisioned user holds the global member floor
    assert renamed.name == "New Name"
    assert local.name == "Local Person" and local.source == UserSource.LOCAL
    assert missing.active is True  # deactivate-missing is OFF by default

    # Idempotent: a second identical pass changes nothing.
    result = await usersync.run_user_sync(db)
    assert (result.provisioned, result.updated, result.deactivated) == (0, 0, 0)


async def test_user_sync_deactivates_missing_only_ldap_when_toggled(
    db, monkeypatch
):
    marker = uuid.uuid4().hex[:8]
    gone_ldap = User(
        email=f"gone-{marker}@dir85.example.com",
        name="Gone",
        password_hash=None,
        source=UserSource.LDAP,
    )
    gone_oidc = User(
        email=f"gone-oidc-{marker}@dir85.example.com",
        name="Gone SSO",
        password_hash=None,
        source=UserSource.OIDC,
    )
    db.add_all([gone_ldap, gone_oidc])
    await db.flush()
    gone_local = await auth_service.create_user(
        db,
        UserCreate(
            email=f"gone-local-{marker}@dir85.example.com", name="Gone Local", password="password-123"
        ),
    )
    await auth_service.create_session(db, gone_ldap, method=LoginMethod.PASSWORD)

    _stub_directory(monkeypatch, [_directory_user("present")])
    await settings_service.set_value(
        db, SettingKey.LDAP_USER_SYNC_DEACTIVATE_MISSING, SettingScope.INSTANCE, None, True
    )

    result = await usersync.run_user_sync(db)
    assert result.deactivated >= 1
    assert gone_ldap.active is False
    remaining = (
        (await db.execute(select(UserSession).where(UserSession.user_id == gone_ldap.id)))
        .scalars()
        .all()
    )
    assert remaining == []  # the session-revoking deactivate (spec 84 semantics)
    # local/oidc accounts missing from the directory are NEVER touched.
    assert gone_local.active is True and gone_oidc.active is True


async def test_user_sync_base_cascade_override_beats_env(db, monkeypatch):
    seen_bases: list[str] = []
    _stub_directory(monkeypatch, [], seen_bases)
    monkeypatch.setattr(config, "ldap_user_search_base", "OU=EnvDefault,DC=dir85,DC=example")

    # The suite runs against a populated dev DB, where a real deploy may already
    # have saved an instance-scope base through the Directory page — which is the
    # very value this first assertion says is absent. Clear it inside the test's
    # rolled-back transaction so configuring the product can't fail its own tests.
    await settings_service.clear_value(
        db, SettingKey.LDAP_USER_SYNC_BASE, SettingScope.INSTANCE, None
    )
    await usersync.run_user_sync(db)
    assert seen_bases[-1] == "OU=EnvDefault,DC=dir85,DC=example"  # env is the cascade default

    await settings_service.set_value(
        db,
        SettingKey.LDAP_USER_SYNC_BASE,
        SettingScope.INSTANCE,
        None,
        "OU=Staff,DC=dir85,DC=example",
    )
    await usersync.run_user_sync(db)
    assert seen_bases[-1] == "OU=Staff,DC=dir85,DC=example"  # instance override wins

    # Resolved-empty falls back to base_dn() at USE time (spec 85 §1).
    await settings_service.set_value(
        db, SettingKey.LDAP_USER_SYNC_BASE, SettingScope.INSTANCE, None, ""
    )
    monkeypatch.setattr(config, "ldap_base_dn", "DC=dir85,DC=example")
    await usersync.run_user_sync(db)
    assert seen_bases[-1] == "DC=dir85,DC=example"


async def test_sync_state_written_and_status_endpoint_shape(db, monkeypatch):
    _stub_directory(monkeypatch, [_directory_user("statecheck")])
    result = await usersync.run_user_sync(db)

    row = await db.get(DirectorySyncState, SyncKind.USER_SYNC.value)
    assert row is not None and row.last_run_at is not None
    assert row.last_result == result.payload()
    assert set(row.last_result) == {"provisioned", "updated", "deactivated", "errors"}

    admin = User(
        email=f"dir85-admin-{uuid.uuid4().hex[:8]}@example.com",
        name="Dir Admin",
        instance_role=InstanceRole.ADMIN.value,
    )
    db.add(admin)
    await db.flush()
    status = await directory_sync_status(db, admin)
    assert status.user_sync is not None
    assert status.user_sync.kind == SyncKind.USER_SYNC.value
    assert status.user_sync.last_result["provisioned"] == result.provisioned
    # group_sync: no loop ran in this session — absent or a real row, never junk.
    assert status.group_sync is None or status.group_sync.kind == SyncKind.GROUP_SYNC.value
