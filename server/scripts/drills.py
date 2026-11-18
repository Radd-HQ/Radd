"""The two operations an operator performs on their worst day, run for real (RADD-1526).

    uv run python scripts/drills.py restore    # backup → empty database → restore → compare
    uv run python scripts/drills.py upgrade    # previous release's data → `alembic upgrade head`
    uv run python scripts/drills.py fixture    # write the fixture `upgrade` starts from

`docs/deploy.md` makes restore the only rollback path, and nothing exercised it:
the backup tests never called restore. Migrations only ever ran against an EMPTY
database, so a migration that fails on existing rows was found in production.

Each drill owns a scratch database (`radd_drill`, dropped and re-created), a
scratch backup directory and a scratch key. It never touches the configured one.

The environment is set BEFORE anything from `radd` is imported, because settings
are read at import; the Alembic and backup CLIs run as child processes with the
same environment, exactly as an operator runs them.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

import psycopg
from sqlalchemy.engine import make_url

_HERE = Path(__file__).resolve().parent.parent
#: Where Alembic and the backup CLI run. Overridable so the very first fixture could
#: be made with the PREVIOUS release's code and migrations from a checkout of its tag
#: (with PYTHONPATH pointing at that checkout's src); normally it is this tree.
SERVER = Path(os.environ.get("RADD_DRILL_SERVER_DIR") or _HERE)
FIXTURES = _HERE / "tests" / "fixtures" / "upgrade"
#: The schema revision the committed fixture was dumped at — the previous release's head.
FIXTURE_NAME = "previous-release.sql"
#: The key the fixture's stored credentials were encrypted with. A TEST key for a
#: throwaway database, committed on purpose: without it the drill could not show that
#: an upgrade leaves encrypted credentials readable.
FIXTURE_KEY_NAME = "previous-release.key"
DRILL_DATABASE = "radd_drill"
SEED_ITEMS = 25
WEBHOOK_URL = "https://example.invalid/drill"


def _base_url() -> str:
    return (
        os.environ.get("RADD_DRILL_DATABASE_URL")
        or os.environ.get("RADD_TEST_DATABASE_URL")
        or os.environ.get("RADD_DATABASE_URL")
        or "postgresql+psycopg://radd:radd@localhost:5455/radd"
    )


DRILL_URL = make_url(_base_url()).set(database=DRILL_DATABASE)
_SCRATCH = Path(tempfile.mkdtemp(prefix="radd-drill-"))
os.environ.update(
    RADD_DATABASE_URL=DRILL_URL.render_as_string(hide_password=False),
    RADD_BACKUP_DIR=str(_SCRATCH / "backups"),
    RADD_BACKUP_KEY_FILE=str(_SCRATCH / "key" / "radd-backup.key"),
    RADD_ATTACHMENTS_DIR=str(_SCRATCH / "attachments"),
)


def _say(message: str) -> None:
    print(f"drill: {message}", flush=True)


def _connection(database: str) -> psycopg.Connection:
    return psycopg.connect(
        host=DRILL_URL.host, port=DRILL_URL.port, user=DRILL_URL.username,
        password=DRILL_URL.password, dbname=database, autocommit=True,
    )


def _admin_connection() -> psycopg.Connection:
    return _connection("postgres")


def _drill_connection() -> psycopg.Connection:
    return _connection(DRILL_DATABASE)


def drop_database() -> None:
    with _admin_connection() as connection:
        connection.execute(f'DROP DATABASE IF EXISTS "{DRILL_DATABASE}" WITH (FORCE)')


def recreate_database() -> None:
    drop_database()
    with _admin_connection() as connection:
        connection.execute(f'CREATE DATABASE "{DRILL_DATABASE}"')


def run(*command: str) -> None:
    _say("$ " + " ".join(command))
    subprocess.run(command, cwd=SERVER, check=True, env=os.environ)


def migrate(revision: str = "head") -> None:
    run(sys.executable, "-m", "alembic", "upgrade", revision)


def fingerprint() -> dict[str, tuple[int, str]]:
    """Every table's row count and an order-independent digest of its rows."""
    with _drill_connection() as connection:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY 1"
            )
        ]
        return {
            table: connection.execute(
                f"SELECT count(*), md5(coalesce(string_agg(md5(t::text), '' ORDER BY md5(t::text)), '')) "  # noqa: S608
                f'FROM "{table}" t'
            ).fetchone()
            for table in tables
        }


def compare(before: dict, after: dict) -> list[str]:
    problems = []
    for table in sorted(set(before) | set(after)):
        if table not in after:
            problems.append(f"{table}: missing after")
        elif table not in before:
            if after[table][0]:
                problems.append(f"{table}: appeared with {after[table][0]} rows")
        elif before[table] != after[table]:
            problems.append(f"{table}: {before[table][0]} rows before, {after[table][0]} after"
                            + ("" if before[table][0] != after[table][0] else " (same count, different content)"))
    return problems


async def seed() -> str:
    """Representative rows through the product's own services: an admin, a project,
    issues, comments, and a webhook whose secret is encrypted at rest. Returns the
    webhook's plaintext secret, to prove after a restore that the key still opens it.

    Only long-stable service calls: this also runs under the PREVIOUS release's
    code when the upgrade fixture is made."""
    from radd import secretbox
    from radd.config import settings
    from radd.db import SessionLocal, engine
    from radd.kernel import load_plugins
    from radd.modules.comments import service as comments
    from radd.modules.comments.schemas import CommentCreate
    from radd.modules.items import service as items
    from radd.modules.items.schemas import ItemCreate
    from radd.modules.projects import service as projects
    from radd.modules.projects.schemas import ProjectCreate
    from radd.modules.auth import service as auth
    from radd.modules.webhooks import service as webhooks
    from radd.modules.webhooks.schemas import EndpointCreate
    from radd.seed import seed as seed_admin

    load_plugins(settings.modules)  # the registries a request would find filled at boot
    await seed_admin("drill-admin@example.com", "drill-password-123", "Drill Admin")
    async with SessionLocal() as session:
        admin = await auth.get_user_by_email(session, "drill-admin@example.com")
        project = await projects.create_project(
            session, ProjectCreate(key="DRILL", name="Drill"), actor_id=admin.id
        )
        for index in range(SEED_ITEMS):
            item = await items.create_item(
                session, ItemCreate(project_id=project.id, title=f"Drill item {index}"), admin
            )
            if index % 5 == 0:
                await comments.create_comment(
                    session, item.id, CommentCreate(body=f"Comment on {index}"), admin
                )
        endpoint = await webhooks.create_endpoint(
            session, EndpointCreate(url=WEBHOOK_URL, description="drill"), actor_id=admin.id
        )
        secret = secretbox.decrypt(endpoint.secret)
        await session.commit()
    await engine.dispose()
    return secret


async def _stored_webhook_secret() -> str:
    from sqlalchemy import text

    from radd import secretbox
    from radd.db import engine

    async with engine.connect() as connection:
        stored = (
            await connection.execute(
                text("SELECT secret FROM webhook_endpoints WHERE url = :url"), {"url": WEBHOOK_URL}
            )
        ).scalar_one()
    await engine.dispose()
    return secretbox.decrypt(stored)


def _fail(title: str, problems: list[str]) -> int:
    _say(f"FAILED — {title}")
    for problem in problems:
        _say(f"  {problem}")
    return 1


# --- restore ---


def drill_restore() -> int:
    recreate_database()
    migrate()
    secret = asyncio.run(seed())
    before = fingerprint()
    rows = sum(count for count, _ in before.values())
    _say(f"seeded {rows} rows across {sum(1 for c, _ in before.values() if c)} non-empty tables")

    run(sys.executable, "-m", "radd.backup", "create", "--no-attachments")
    names = sorted(p.name for p in Path(os.environ["RADD_BACKUP_DIR"]).iterdir() if p.suffix == ".radd")
    if len(names) != 1:
        return _fail("expected exactly one artifact", names)

    # The disaster: nothing left but the artifact and the key.
    recreate_database()
    run(sys.executable, "-m", "radd.backup", "restore", names[0], "--yes")

    problems = compare(before, fingerprint())
    if problems:
        return _fail("the restored database differs from the one that was backed up", problems)
    if asyncio.run(_stored_webhook_secret()) != secret:
        return _fail("a stored credential did not decrypt after the restore", [])
    _say(f"OK — {rows} rows restored identically; an encrypted credential still decrypts")
    return 0


# --- upgrade ---


def _load_sql(path: Path) -> None:
    # psql meta-commands (pg_dump 17.6+ writes \restrict) are not SQL.
    statements = "\n".join(
        line for line in path.read_text().splitlines() if not line.startswith("\\")
    )
    with _drill_connection() as connection:
        connection.execute(statements)


def drill_upgrade() -> int:
    fixture = FIXTURES / FIXTURE_NAME
    if not fixture.exists():
        return _fail(f"no fixture at {fixture}", ["run: scripts/drills.py fixture"])
    recreate_database()
    _load_sql(fixture)
    key_file = Path(os.environ["RADD_BACKUP_KEY_FILE"])
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_bytes((FIXTURES / FIXTURE_KEY_NAME).read_bytes())
    key_file.chmod(0o600)
    with _drill_connection() as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    before = fingerprint()
    rows = sum(count for count, _ in before.values())
    _say(f"loaded {fixture.name}: revision {revision}, {rows} rows")

    migrate()

    after = fingerprint()
    # A migration may rewrite rows (that is its job); it must not LOSE them.
    lost = [
        f"{table}: {before[table][0]} rows before the upgrade, {after[table][0]} after"
        for table in sorted(before)
        if table in after and table != "alembic_version" and after[table][0] < before[table][0]
    ]
    gone = [f"{table}: table dropped with {before[table][0]} rows in it"
            for table in sorted(before) if table not in after and before[table][0]]
    if lost or gone:
        return _fail("the upgrade lost rows", lost + gone)
    problems = asyncio.run(_upgraded_instance_works())
    if problems:
        return _fail("the upgraded database does not serve", problems)
    _say(f"OK — upgraded from {revision} to head with {rows} rows in place; the app starts on it")
    return 0


async def _upgraded_instance_works() -> list[str]:
    """Boot the real application on the upgraded data and read through its services."""
    os.environ["RADD_BACKUP_TOOLS_OPTIONAL"] = "true"
    from radd.app import create_app
    from radd.db import SessionLocal, engine
    from radd.modules.auth import service as auth
    from radd.modules.events import service as events
    from radd.modules.items import service as items
    from radd.modules.items.schemas import ItemCreate
    from radd.modules.projects import service as projects

    problems: list[str] = []
    app = create_app()
    async with app.router.lifespan_context(app):
        async with SessionLocal() as session:
            admin = await auth.get_user_by_email(session, "drill-admin@example.com")
            project = await projects.get_by_key(session, "DRILL")
            if admin is None or project is None:
                return ["the seeded admin or project is not readable after the upgrade"]
            # Old events sort before every new one, so a consumer neither replays nor skips.
            start = await events.head_cursor(session)
            created = await items.create_item(
                session, ItemCreate(project_id=project.id, title="Created after the upgrade"), admin
            )
            fresh = await events.read_after(session, start, 50)
            if not any(e.entity_id == str(created.id) for e in fresh):
                problems.append("an event written after the upgrade is not readable by a consumer")
            if any(e.xact_id == 0 for e in fresh):
                problems.append("a pre-upgrade event was replayed to a consumer at the head")
            await session.rollback()
    await engine.dispose()
    try:
        if not await _stored_webhook_secret():
            problems.append("the fixture's stored credential decrypted to nothing")
    except Exception as error:  # noqa: BLE001 — any failure to decrypt is the finding
        problems.append(f"a credential stored before the upgrade no longer decrypts: {error}")
    return problems


# --- fixture ---


def make_fixture() -> int:
    """Dump a seeded database at the CURRENT head. Run it on the release commit,
    commit the file, and the NEXT release's migrations are tested against it."""
    recreate_database()
    migrate()
    asyncio.run(seed())
    FIXTURES.mkdir(parents=True, exist_ok=True)
    command = shlex.split(os.environ.get("RADD_DRILL_PG_DUMP", "pg_dump"))
    url = os.environ.get("RADD_DRILL_PG_DUMP_URL") or DRILL_URL.set(
        drivername="postgresql"
    ).render_as_string(hide_password=False)
    _say("$ " + " ".join(command) + " --inserts …")
    dump = subprocess.run(
        [*command, "--inserts", "--no-owner", "--no-acl", f"--dbname={url}"],
        check=True, capture_output=True, text=True,
    ).stdout
    (FIXTURES / FIXTURE_NAME).write_text(dump)
    (FIXTURES / FIXTURE_KEY_NAME).write_bytes(Path(os.environ["RADD_BACKUP_KEY_FILE"]).read_bytes())
    _say(f"wrote {FIXTURES / FIXTURE_NAME} ({len(dump) // 1024} KiB)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("drill", choices=("restore", "upgrade", "fixture"))
    parser.add_argument("--keep", action="store_true", help="leave the scratch database in place")
    args = parser.parse_args()
    try:
        return {"restore": drill_restore, "upgrade": drill_upgrade, "fixture": make_fixture}[args.drill]()
    finally:
        if not args.keep:
            drop_database()


if __name__ == "__main__":
    sys.exit(main())
