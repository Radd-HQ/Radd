"""Shared test setup.

Database: the suite is SELF-CONTAINED. Before any test module is imported, this
conftest repoints the app at a throwaway `radd_test` database (same Postgres
server as the configured `settings.database_url`; override the whole URL via
RADD_TEST_DATABASE_URL), and a session-scoped fixture re-creates it and migrates
it to head. The dev database is never touched — setup refuses to run when the
resolved test URL names the same database as the configured dev URL.

The kernel contribution registries (event types, triggers, capabilities, …) are
*boot state*: `create_app()` populates them by calling `load_plugins`. Unit tests
that exercise services directly without booting the app still need that state —
e.g. `automations.catalog.TRIGGERS` is derived live from the event-type registry
(spec 93, chokepoint-1 inversion). This autouse fixture loads the full plugin set
before every test, exactly as the app does at startup, so the registry is always
the complete, current boot state regardless of any test that reloads it.

Cheap: module imports are cached, so this is a dict rebuild per test.
"""

import os
from pathlib import Path

import psycopg
import pytest
from sqlalchemy.engine import make_url

# --- Throwaway test database --------------------------------------------------
# Must run BEFORE anything imports `radd.db`: the engine and SessionLocal are
# built from `settings.database_url` at import time. conftest is imported before
# every test module, so setting RADD_DATABASE_URL here (plus mutating the
# settings singleton) covers radd.db, alembic's env.py, and the per-file
# fixtures that build engines from `settings.database_url` at runtime.
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
    """Seed the builtin roles, exactly as app startup does.

    Not optional since RADD-773. What every active user holds is the BASELINE
    role row now, not a constant — so a database without it gives every actor an
    empty permission set, and tests that touch a real session then behave
    differently depending on whether some earlier test happened to seed it.

    That is not hypothetical: `pytest tests/test_portal.py` alone failed with
    "item.read denied" while the full suite passed, because another module's
    fixture had seeded the row first. A suite whose result depends on which
    subset you run is worse than one that fails.
    """
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

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


from radd.kernel import load_plugins  # noqa: E402


@pytest.fixture(autouse=True)
def _kernel_registries_loaded():
    load_plugins(settings.modules)
    yield
