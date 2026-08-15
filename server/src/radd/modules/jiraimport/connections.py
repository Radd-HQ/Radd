"""Jira connections (spec 100) — CRUD, default resolution, and env seeding.

Replaces the env-only configuration of spec 90, which could name exactly one
instance and needed a restart to change. Everything downstream (discovery,
snapshot downloads) resolves a connection through here and then works from a
`JiraCreds` value object, never the ORM row — REST calls run in worker threads.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import SessionLocal
from radd.exceptions import ConflictError, NotFoundError

from .models import JiraConnection
from .schemas import JiraConnectionCreate, JiraConnectionUpdate
from .types import JiraAuthMode, JiraConnectionSource, JiraCreds, JiraEntity

logger = logging.getLogger(__name__)

# Update payloads leave the credential alone when this is what came in — a form
# that round-trips a redacted read must not blank the stored token.
UNCHANGED_CREDENTIAL = ""


def placeholder_email_domain(connection: JiraConnection) -> str:
    """The domain for synthesizing an address when Jira exposes none (spec 100).

    An explicit setting wins; otherwise it is DERIVED from the connection's own
    host — `jira.internal.example.com` → `example.com` — because a Jira instance
    almost always lives under the organisation's own domain, which is the domain
    the directory uses. That is what lets a later AD import match on email and
    adopt the placeholder's work (spec 88).

    Spec 90 hardcoded one company's domain in source and wrote it into real user
    rows on every deploy. Deriving it is right far more often, and wrong visibly
    rather than silently — the Users step shows the address before anything is
    created.
    """
    configured = settings.jira_placeholder_email_domain.strip().lstrip("@")
    if configured:
        return configured.lower()
    host = connection.base_url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    labels = [label for label in host.split(".") if label]
    # Last two labels: the registrable domain for the common cases. A host with no
    # dot (a bare intranet name) yields nothing rather than a nonsense domain.
    return ".".join(labels[-2:]).lower() if len(labels) >= 2 else ""


def creds_of(connection: JiraConnection) -> JiraCreds:
    """The thread-safe value object for one connection row."""
    return JiraCreds(
        base_url=connection.base_url,
        auth_mode=JiraAuthMode(connection.auth_mode),
        credential=connection.credential,
        username=connection.username,
        verify_ssl=connection.verify_ssl,
        timeout_seconds=settings.jira_timeout_seconds,
    )


# --- reads --------------------------------------------------------------------


async def list_connections(session: AsyncSession) -> list[JiraConnection]:
    result = await session.execute(
        select(JiraConnection).order_by(
            JiraConnection.is_default.desc(), JiraConnection.name
        )
    )
    return list(result.scalars())


async def get_connection(session: AsyncSession, connection_id: uuid.UUID) -> JiraConnection:
    connection = await session.get(JiraConnection, connection_id)
    if connection is None:
        raise NotFoundError(JiraEntity.CONNECTION, connection_id)
    return connection


async def default_connection(session: AsyncSession) -> JiraConnection | None:
    """The flagged default, else the only one, else None. Falling back to a lone
    connection means a single-instance deploy never has to think about the flag."""
    connections = await list_connections(session)
    if not connections:
        return None
    for connection in connections:
        if connection.is_default:
            return connection
    return connections[0] if len(connections) == 1 else None


async def require_connection(
    session: AsyncSession, connection_id: uuid.UUID | None = None
) -> JiraConnection:
    """The named connection, or the default. 409 (not 404) when none exists: the
    caller is allowed, a piece of the DEPLOY is missing — the ldap convention."""
    if connection_id is not None:
        return await get_connection(session, connection_id)
    connection = await default_connection(session)
    if connection is None:
        raise ConflictError(
            JiraEntity.JIRA,
            reason="no Jira connection is configured — add one under Settings → Import from Jira",
        )
    return connection


# --- writes -------------------------------------------------------------------


async def create_connection(
    session: AsyncSession,
    data: JiraConnectionCreate,
    *,
    source: JiraConnectionSource = JiraConnectionSource.USER,
) -> JiraConnection:
    await _ensure_name_free(session, data.name)
    connection = JiraConnection(
        name=data.name,
        base_url=str(data.base_url).rstrip("/"),
        auth_mode=data.auth_mode.value,
        username=data.username,
        credential=data.credential,
        verify_ssl=data.verify_ssl,
        source=source.value,
    )
    session.add(connection)
    await session.flush()
    # First connection in is the default, so a single-connection deploy is complete
    # the moment it is created.
    if data.is_default or await _count(session) == 1:
        await _make_default(session, connection)
    return connection


async def update_connection(
    session: AsyncSession, connection_id: uuid.UUID, data: JiraConnectionUpdate
) -> JiraConnection:
    connection = await get_connection(session, connection_id)
    fields = data.model_dump(exclude_unset=True)
    if "name" in fields and fields["name"] != connection.name:
        await _ensure_name_free(session, fields["name"])
        connection.name = fields["name"]
    if "base_url" in fields:
        connection.base_url = str(fields["base_url"]).rstrip("/")
    if "auth_mode" in fields:
        connection.auth_mode = JiraAuthMode(fields["auth_mode"]).value
    if "username" in fields:
        connection.username = fields["username"]
    # An empty credential means "keep the stored one" — the read shape is redacted,
    # so a form that saves an untouched connection sends nothing back.
    if fields.get("credential"):
        connection.credential = fields["credential"]
    if "verify_ssl" in fields:
        connection.verify_ssl = fields["verify_ssl"]
    await session.flush()
    if fields.get("is_default"):
        await _make_default(session, connection)
    return connection


async def delete_connection(session: AsyncSession, connection_id: uuid.UUID) -> None:
    connection = await get_connection(session, connection_id)
    was_default = connection.is_default
    await session.delete(connection)
    await session.flush()
    if was_default:  # promote another so a multi-connection deploy keeps a default
        remaining = await list_connections(session)
        if remaining:
            await _make_default(session, remaining[0])


async def _make_default(session: AsyncSession, connection: JiraConnection) -> None:
    """Exactly one default. Cleared in one statement rather than per row so the
    invariant cannot be left half-applied."""
    await session.execute(
        update(JiraConnection)
        .where(JiraConnection.id != connection.id)
        .values(is_default=False)
    )
    connection.is_default = True
    await session.flush()


async def _ensure_name_free(session: AsyncSession, name: str) -> None:
    result = await session.execute(select(JiraConnection).where(JiraConnection.name == name))
    if result.scalar_one_or_none() is not None:
        raise ConflictError(JiraEntity.CONNECTION, reason=f"a connection named {name!r} exists")


async def _count(session: AsyncSession) -> int:
    result = await session.execute(select(JiraConnection.id))
    return len(list(result.scalars()))


# --- env seeding (startup) ----------------------------------------------------


async def seed_from_env() -> None:
    """Turn a spec-90 environment configuration into a real connection row, ONCE.

    Runs only when the table is empty, so an admin who deletes or renames the
    seeded row never has it silently reappear. Seeded rows are ordinary editable
    connections — being able to fix the URL without a redeploy is the point.
    """
    base_url = settings.jira_base_url.strip()
    if not base_url:
        return
    pat = settings.jira_pat.strip()
    user, password = settings.jira_user.strip(), settings.jira_password
    if pat:
        mode, username, credential = JiraAuthMode.PAT, "", pat
    elif user and password:
        mode, username, credential = JiraAuthMode.BASIC, user, password
    else:
        return
    async with SessionLocal() as session:
        if await _count(session) > 0:
            return
        await create_connection(
            session,
            JiraConnectionCreate(
                name=_seed_name(base_url),
                base_url=base_url,
                auth_mode=mode,
                username=username,
                credential=credential,
                verify_ssl=settings.jira_verify_ssl,
                is_default=True,
            ),
            source=JiraConnectionSource.ENV,
        )
        await session.commit()
    logger.info("jiraimport: seeded a Jira connection for %s from the environment", base_url)


def _seed_name(base_url: str) -> str:
    """Name the seeded row after its host, so a deploy with several instances over
    time reads sensibly rather than showing a row called "default"."""
    host = base_url.split("://", 1)[-1].split("/", 1)[0]
    return host or "Jira"
