"""Shared test setup.

The suite runs against a throwaway `radd_test` database (override with
RADD_TEST_DATABASE_URL), re-created and migrated once per session; setup refuses
a URL naming the dev database. This must run before anything imports `radd.db`,
whose engine is built from `settings.database_url` at import time.

The kernel registries are boot state `create_app()` fills via `load_plugins`;
the autouse fixture reloads the full plugin set before every test.
"""

import os
from pathlib import Path

import psycopg
import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# --- Throwaway test database --------------------------------------------------
# Must run before anything imports radd.db (see the module docstring).
from radd.config import settings  # noqa: E402

_TEST_DB_NAME = "radd_test"


def _resolve_test_database_url() -> str:
    dev = make_url(settings.database_url)
    override = os.environ.get("RADD_TEST_DATABASE_URL")
    test = make_url(override) if override else dev.set(database=_TEST_DB_NAME)
    if (test.host, test.port, test.database) == (dev.host, dev.port, dev.database):
        raise RuntimeError(
            "Refusing to run the test suite against the dev database "
            f"({dev.render_as_string(hide_password=True)}). "
            "Point RADD_TEST_DATABASE_URL at a throwaway database."
        )
    return test.render_as_string(hide_password=False)


TEST_DATABASE_URL = _resolve_test_database_url()
os.environ["RADD_DATABASE_URL"] = TEST_DATABASE_URL
settings.database_url = TEST_DATABASE_URL


def _recreate_database() -> None:
    """DROP + CREATE the test database through the server's maintenance db."""
    url = make_url(TEST_DATABASE_URL)
    conn = psycopg.connect(
        host=url.host,
        port=url.port,
        user=url.username,
        password=url.password,
        dbname="postgres",
        autocommit=True,
    )
    try:
        # FORCE kicks leftover sessions from an interrupted run (Postgres 13+).
        with conn.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)')
            cur.execute(f'CREATE DATABASE "{url.database}"')
    finally:
        conn.close()


def _migrate_database() -> None:
    """`alembic upgrade head`, programmatic — env.py picks up the overridden settings."""
    from alembic import command
    from alembic.config import Config

    server_dir = Path(__file__).resolve().parent.parent
    cfg = Config(str(server_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(server_dir / "migrations"))
    command.upgrade(cfg, "head")


def _seed_builtin_roles() -> None:
    """Seed the builtin roles as startup does. Required: every user's floor is the
    Baseline ROW (RADD-773), so without it a test's permissions depend on whether an
    earlier test happened to seed it."""
    import asyncio

    from radd.modules.auth import roles

    async def run() -> None:
        engine = create_async_engine(settings.database_url)
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await roles.ensure_builtin_roles(session)
            await session.commit()
        await engine.dispose()

    asyncio.run(run())


@pytest.fixture(scope="session", autouse=True)
def isolated_encryption_key(tmp_path_factory):
    """Cursor tests must never depend on or create the instance's real key."""
    from radd import secretbox

    original = settings.backup_key_file
    settings.backup_key_file = str(tmp_path_factory.mktemp("encryption") / "key")
    secretbox.reset_key_cache()
    try:
        yield
    finally:
        secretbox.reset_key_cache()
        settings.backup_key_file = original


@pytest.fixture(scope="session", autouse=True)
def _fresh_test_database():
    _recreate_database()
    _migrate_database()
    _seed_builtin_roles()
    yield


from _factories import make_user  # noqa: E402
from radd.kernel import load_plugins  # noqa: E402
from radd.modules.auth.types import InstanceRole  # noqa: E402


@pytest.fixture(autouse=True)
def _kernel_registries_loaded():
    load_plugins(settings.modules)
    yield


@pytest.fixture
async def db():
    """A session on the test database; everything it wrote is rolled back."""
    engine = create_async_engine(settings.database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def admin(db):
    """An instance admin."""
    return await make_user(db, role=InstanceRole.ADMIN, name="Admin")


@pytest.fixture
def actor(admin):
    """`admin`, under the name the item tests give whoever acts."""
    return admin
