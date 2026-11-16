"""Driving `pg_dump` / `pg_restore` (spec 99 §3).

Credentials reach the subprocess as **libpq environment variables**, never on
argv: `/proc/<pid>/cmdline` is world-readable, so a password in the command line
is a password every local account can read. `PGPASSWORD` in the child's env is
not visible to other users.

`pg_dump` is a runtime requirement, not a capability that degrades — a backup
system that silently cannot back up is worse than one that refuses to start. The
pre-flight runs at startup and fails loudly; `backup_tools_optional` downgrades
it to a warning for dev boxes without a Postgres client.

The client major must be >= the server it dumps (a 15 client cannot dump a 16
server). The image's client is usually NEWER than the server, and that has a
cost on the way back in (RADD-1543): a newer `pg_dump` writes session settings
an older server does not know (`transaction_timeout`, new in 17), and one
unknown `SET` aborted the whole single-transaction restore — every backup
"verified", none restorable. `restore_from` therefore replays the archive as SQL
with the settings the SERVER does not have removed from its header.
"""

import asyncio
import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.engine import make_url

from radd.config import settings

from .errors import BackupError

logger = logging.getLogger(__name__)

_VERSION_RE = re.compile(r"(\d+)(?:\.(\d+))?")


class PgToolError(BackupError):
    """A tool is missing, too old, or exited non-zero."""


@dataclass(frozen=True)
class ToolInfo:
    path: str | None
    version: str | None
    major: int | None


@dataclass(frozen=True)
class ToolStatus:
    """What `GET /backups/status` shows and what the pre-flight checks."""

    pg_dump: ToolInfo
    pg_restore: ToolInfo
    problem: str | None
    #: Restore applies the archive through psql (RADD-1543); same client package.
    psql: ToolInfo | None = None

    @property
    def available(self) -> bool:
        return self.problem is None


def _connection_env() -> dict[str, str]:
    """libpq env for the child process — the password never touches argv."""
    url = make_url(settings.database_url)
    env: dict[str, str] = {}
    if url.host:
        env["PGHOST"] = url.host
    if url.port:
        env["PGPORT"] = str(url.port)
    if url.username:
        env["PGUSER"] = url.username
    if url.password:
        env["PGPASSWORD"] = str(url.password)
    if url.database:
        env["PGDATABASE"] = url.database
    return env


def database_name() -> str:
    return make_url(settings.database_url).database or ""


async def _run(program: str, *args: str, stdin_path: Path | None = None) -> bytes:
    """Run a tool with libpq env, returning stdout or raising with its stderr."""
    import os

    process = await asyncio.create_subprocess_exec(
        program,
        *args,
        stdin=stdin_path.open("rb") if stdin_path else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, **_connection_env()},
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=settings.backup_timeout_seconds
        )
    except TimeoutError:
        process.kill()
        raise PgToolError(
            f"{Path(program).name} exceeded {settings.backup_timeout_seconds}s"
        ) from None
    if process.returncode != 0:
        detail = stderr.decode(errors="replace").strip().splitlines()
        raise PgToolError(f"{Path(program).name} failed: {detail[-1] if detail else '(no output)'}")
    return stdout


async def _tool_info(configured: str) -> ToolInfo:
    path = shutil.which(configured) or (configured if Path(configured).is_file() else None)
    if path is None:
        return ToolInfo(None, None, None)
    try:
        raw = (await _run(path, "--version")).decode().strip()
    except PgToolError:
        return ToolInfo(path, None, None)
    # `pg_dump (PostgreSQL) 17.10 (Debian 17.10-0+deb13u1)` — take the first
    # version-shaped token, not the last word, which is a packaging suffix.
    match = _VERSION_RE.search(raw)
    return ToolInfo(path, match.group(0) if match else None, int(match.group(1)) if match else None)


async def server_major() -> int | None:
    """The server's major version, read over the app's own connection."""
    from sqlalchemy import text

    from radd.db import engine

    async with engine.connect() as connection:
        raw = (await connection.execute(text("SHOW server_version"))).scalar_one()
    match = _VERSION_RE.search(str(raw))
    return int(match.group(1)) if match else None


async def server_version() -> str:
    from sqlalchemy import text

    from radd.db import engine

    async with engine.connect() as connection:
        return str((await connection.execute(text("SHOW server_version"))).scalar_one())


async def tool_status() -> ToolStatus:
    """Resolve both tools and decide whether backups can run at all."""
    dump = await _tool_info(settings.backup_pg_dump_path)
    restore = await _tool_info(settings.backup_pg_restore_path)
    problem: str | None = None
    psql = await _tool_info(settings.backup_psql_path)
    missing = [
        name
        for name, info in (("pg_dump", dump), ("pg_restore", restore), ("psql", psql))
        if info.path is None
    ]
    if missing:
        problem = (
            f"{' and '.join(missing)} not found — install the PostgreSQL client "
            f"(the container image ships postgresql-client; a backup needs pg_dump, "
            f"a restore needs pg_restore and psql)"
        )
    else:
        try:
            server = await server_major()
        except Exception:  # noqa: BLE001 — status must never raise
            server = None
        if server and dump.major and dump.major < server:
            problem = (
                f"pg_dump {dump.major} is older than the server ({server}); "
                f"a dump requires a client at least as new as the server"
            )
    return ToolStatus(dump, restore, problem, psql)


async def preflight() -> None:
    """Startup gate. Refuses to boot unless `backup_tools_optional`."""
    status = await tool_status()
    if status.available:
        logger.info(
            "backups ready: pg_dump %s, pg_restore %s",
            status.pg_dump.version,
            status.pg_restore.version,
        )
        return
    if settings.backup_tools_optional:
        logger.warning("backups DISABLED: %s (RADD_BACKUP_TOOLS_OPTIONAL is set)", status.problem)
        return
    raise RuntimeError(
        f"Radd cannot start: {status.problem}. Set RADD_BACKUP_TOOLS_OPTIONAL=true "
        f"to start without a working backup system."
    )


async def dump_to(path: Path) -> None:
    """`pg_dump -Fc` into `path` (compressed by pg_dump itself)."""
    await _run(
        settings.backup_pg_dump_path,
        "--format=custom",
        f"--compress={settings.backup_compression}",
        "--no-owner",
        "--no-acl",
        f"--file={path}",
    )


#: How much of the script is examined for session settings. The header (a block of
#: `SET` lines before the first object) is a few hundred bytes; nothing past this
#: is ever rewritten, so a row of table data that reads like a `SET` is safe.
_HEADER_BYTES = 16 * 1024
_SET_LINE = re.compile(rb"^SET ([a-z_.]+) = [^\n]*;\r?\n", re.MULTILINE)


def strip_unknown_settings(header: bytes, known: set[str]) -> bytes:
    """Drop `SET name = …;` lines whose `name` this server does not have.

    Pure, and deliberately keyed on what the SERVER knows rather than on a list
    of settings: the next PostgreSQL release will add another one."""

    def keep(match: re.Match[bytes]) -> bytes:
        name = match.group(1).decode()
        if name in known or "." in name:  # extension settings (`a.b`) are not in pg_settings
            return match.group(0)
        logger.info("restore: dropping `SET %s` — this server has no such setting", name)
        return b""

    return _SET_LINE.sub(keep, header)


async def _server_settings() -> set[str]:
    from sqlalchemy import text

    from radd.db import engine

    async with engine.connect() as connection:
        return {row[0] for row in await connection.execute(text("SELECT name FROM pg_settings"))}


async def restore_from(path: Path) -> None:
    """Replay the archive into the (already emptied) database, all or nothing.

    `pg_restore` turns the archive into SQL and `psql` applies it in ONE
    transaction with ON_ERROR_STOP, so the all-or-nothing guarantee is unchanged.
    What changes is that the two no longer have to agree on every session setting
    (RADD-1543, see the module docstring)."""
    import os

    known = await _server_settings()
    env = {**os.environ, **_connection_env()}
    source = await asyncio.create_subprocess_exec(
        settings.backup_pg_restore_path, "--no-owner", "--no-acl", "--file=-", str(path),
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, env=env,
    )
    sink = await asyncio.create_subprocess_exec(
        settings.backup_psql_path, "--quiet", "--no-psqlrc", "--single-transaction",
        "--set=ON_ERROR_STOP=1", f"--dbname={database_name()}",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE, env=env,
    )

    async def pump() -> None:
        assert source.stdout is not None and sink.stdin is not None
        try:
            header = b""
            while len(header) < _HEADER_BYTES:
                chunk = await source.stdout.read(_HEADER_BYTES - len(header))
                if not chunk:
                    break
                header += chunk
            # Cut at a line boundary so a `SET` line split across the edge is whole.
            edge = header.rfind(b"\n") + 1
            sink.stdin.write(strip_unknown_settings(header[:edge], known) + header[edge:])
            await sink.stdin.drain()
            while chunk := await source.stdout.read(1 << 20):
                sink.stdin.write(chunk)
                await sink.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass  # psql stopped on an error; its stderr says why
        finally:
            sink.stdin.close()

    async def drain(stream: asyncio.StreamReader | None) -> str:
        return (await stream.read()).decode(errors="replace") if stream else ""

    try:
        _, source_err, sink_err, source_code, sink_code = await asyncio.wait_for(
            asyncio.gather(pump(), drain(source.stderr), drain(sink.stderr), source.wait(), sink.wait()),
            timeout=settings.backup_timeout_seconds,
        )
    except TimeoutError:
        for process in (source, sink):
            if process.returncode is None:
                process.kill()
        raise PgToolError(f"restore exceeded {settings.backup_timeout_seconds}s") from None
    for name, code, err in (("psql", sink_code, sink_err), ("pg_restore", source_code, source_err)):
        if code != 0:
            detail = [line for line in err.strip().splitlines() if line.strip()]
            raise PgToolError(f"{name} failed: {detail[-1] if detail else '(no output)'}")


async def list_dump(path: Path) -> int:
    """`pg_restore --list` — proves the dump is readable. Returns entry count.

    This is the verification pass every finished artifact goes through, so
    "verified" on the backups page is a fact rather than a hope."""
    output = await _run(settings.backup_pg_restore_path, "--list", str(path))
    return sum(1 for line in output.decode(errors="replace").splitlines() if line and line[0].isdigit())


async def terminate_other_backends() -> int:
    """Disconnect everything else on this database, so the schema can be dropped.

    This kills OUR OWN pooled connections too — `pg_terminate_backend` spares only
    the backend issuing it, and SQLAlchemy holds a pool of the rest. So the pool is
    disposed immediately after: without that, the very next statement checks out a
    connection the server has already terminated and fails with AdminShutdown.
    """
    from sqlalchemy import text

    from radd.db import engine

    async with engine.connect() as connection:
        result = await connection.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = current_database() AND pid <> pg_backend_pid()"
            )
        )
        await connection.commit()
        terminated = len(result.all())
    await dispose_pool()
    return terminated


async def dispose_pool() -> None:
    """Drop every pooled connection so the next checkout is a fresh one.

    Needed on both sides of a restore: before, because we just terminated those
    connections; after, because they were opened against a schema that no longer
    exists (cached plans and type OIDs both go stale)."""
    from radd.db import engine

    await engine.dispose()


async def drop_public_schema() -> None:
    """Empty the database deterministically.

    `pg_restore --clean` only drops what the dump CONTAINS, so tables added by
    later migrations would survive into a supposedly restored database. Dropping
    the schema ourselves leaves nothing behind."""
    from sqlalchemy import text

    from radd.db import engine

    async with engine.connect() as connection:
        await connection.execute(text("DROP SCHEMA public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
        await connection.commit()


async def database_bytes() -> int:
    from sqlalchemy import text

    from radd.db import engine

    async with engine.connect() as connection:
        return int((await connection.execute(text("SELECT pg_database_size(current_database())"))).scalar_one())
