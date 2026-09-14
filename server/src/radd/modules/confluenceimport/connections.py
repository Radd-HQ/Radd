"""Confluence connections (spec 117) — CRUD, default resolution, env seeding.

The `jiraimport.connections` shape, deliberately: same exactly-one-default
invariant, same redacted-credential contract, same seed-once rule. Everything
downstream resolves a connection here and then works from a `ConfluenceCreds`
value object, never the ORM row — REST calls run in worker threads.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import SessionLocal
from radd.kernel import changes
from radd.modules.events import service as events
from radd.exceptions import ConflictError, NotFoundError

from .models import ConfluenceConnection
from .schemas import ConnectionCreate, ConnectionUpdate
from .types import ConfluenceEvent, ConfluenceAuthMode, ConfluenceCreds, ConfluenceEntity, ConnectionSource

logger = logging.getLogger(__name__)


def placeholder_email_domain(connection: ConfluenceConnection) -> str:
    """The domain for synthesizing an address when Confluence exposes none.

    An explicit setting wins; otherwise DERIVED from the connection's own host, on
    the same reasoning as the Jira importer: a wiki lives under the organisation's
    domain, which is the domain the directory uses, so a placeholder address is
    what a later AD import matches on to adopt the placeholder's work (spec 88).
    """
    configured = settings.confluence_placeholder_email_domain.strip().lstrip("@")
    if configured:
        return configured.lower()
    host = connection.base_url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    labels = [label for label in host.split(".") if label]
    return ".".join(labels[-2:]).lower() if len(labels) >= 2 else ""


def creds_of(connection: ConfluenceConnection) -> ConfluenceCreds:
    """The thread-safe value object for one connection row."""
    return ConfluenceCreds(
        base_url=connection.base_url,
        auth_mode=ConfluenceAuthMode(connection.auth_mode),
        credential=connection.credential,
        username=connection.username,
        verify_ssl=connection.verify_ssl,
        timeout_seconds=settings.confluence_timeout_seconds,
    )


# --- reads --------------------------------------------------------------------


async def list_connections(session: AsyncSession) -> list[ConfluenceConnection]:
    result = await session.execute(
        select(ConfluenceConnection).order_by(
            ConfluenceConnection.is_default.desc(), ConfluenceConnection.name
        )
    )
    return list(result.scalars())


async def get_connection(
    session: AsyncSession, connection_id: uuid.UUID
) -> ConfluenceConnection:
    connection = await session.get(ConfluenceConnection, connection_id)
    if connection is None:
        raise NotFoundError(ConfluenceEntity.CONNECTION, connection_id)
    return connection


async def default_connection(session: AsyncSession) -> ConfluenceConnection | None:
    """The flagged default, else the only one, else None — so a single-instance
    deploy never has to think about the flag."""
    connections = await list_connections(session)
    if not connections:
        return None
    for connection in connections:
        if connection.is_default:
            return connection
    return connections[0] if len(connections) == 1 else None


async def require_connection(
    session: AsyncSession, connection_id: uuid.UUID | None = None
) -> ConfluenceConnection:
    """409, not 404, when none exists: the caller is allowed, a piece of the DEPLOY
    is missing — the ldap convention this codebase already follows."""
    if connection_id is not None:
        return await get_connection(session, connection_id)
    connection = await default_connection(session)
    if connection is None:
        raise ConflictError(
            ConfluenceEntity.CONFLUENCE,
            reason="no Confluence connection is configured — add one under "
            "Settings → Import from Confluence",
        )
    return connection


# --- writes -------------------------------------------------------------------


#: Never in an event payload — a diff records that the credential CHANGED, no value.
SECRET_FIELDS: tuple[str, ...] = ("credential",)
_UNDIFFED: tuple[str, ...] = (*changes.DEFAULT_EXCLUDED_COLUMNS, "source")


async def _emit(
    session: AsyncSession,
    event_type: ConfluenceEvent,
    connection: ConfluenceConnection,
    actor_id: uuid.UUID | None,
    diff: list[dict] | None = None,
) -> None:
    await events.emit(
        session,
        event_type=event_type,
        entity_type=ConfluenceEntity.CONNECTION,
        entity_id=connection.id,
        actor_id=actor_id,
        payload={"name": connection.name, "base_url": connection.base_url},
        changes=diff,
    )


async def create_connection(
    session: AsyncSession,
    data: ConnectionCreate,
    *,
    actor_id: uuid.UUID | None = None,
    source: ConnectionSource = ConnectionSource.USER,
) -> ConfluenceConnection:
    await _ensure_name_free(session, data.name)
    connection = ConfluenceConnection(
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
    # First one in is the default, so a single-connection deploy is complete the
    # moment it is created.
    if data.is_default or await _count(session) == 1:
        await _make_default(session, connection)
    await _emit(session, ConfluenceEvent.CONNECTION_CREATED, connection, actor_id)
    return connection


async def update_connection(
    session: AsyncSession,
    connection_id: uuid.UUID,
    data: ConnectionUpdate,
    *,
    actor_id: uuid.UUID | None = None,
) -> ConfluenceConnection:
    connection = await get_connection(session, connection_id)
    before = changes.snapshot(connection, changes.column_fields(connection, exclude=_UNDIFFED))
    fields = data.model_dump(exclude_unset=True)
    if "name" in fields and fields["name"] != connection.name:
        await _ensure_name_free(session, fields["name"])
        connection.name = fields["name"]
    if "base_url" in fields:
        connection.base_url = str(fields["base_url"]).rstrip("/")
    if "auth_mode" in fields:
        connection.auth_mode = ConfluenceAuthMode(fields["auth_mode"]).value
    if "username" in fields:
        connection.username = fields["username"]
    # Empty means "keep the stored one": the read shape is redacted, so a form that
    # saves an untouched connection sends nothing back and must not blank the token.
    if fields.get("credential"):
        connection.credential = fields["credential"]
    if "verify_ssl" in fields:
        connection.verify_ssl = fields["verify_ssl"]
    await session.flush()
    if fields.get("is_default"):
        await _make_default(session, connection)
    await _emit(
        session,
        ConfluenceEvent.CONNECTION_UPDATED,
        connection,
        actor_id,
        changes.diff_object(connection, before, hidden=SECRET_FIELDS),
    )
    return connection


async def delete_connection(
    session: AsyncSession, connection_id: uuid.UUID, *, actor_id: uuid.UUID | None = None
) -> None:
    connection = await get_connection(session, connection_id)
    was_default = connection.is_default
    await _emit(session, ConfluenceEvent.CONNECTION_DELETED, connection, actor_id)
    await session.delete(connection)
    await session.flush()
    if was_default:
        remaining = await list_connections(session)
        if remaining:
            await _make_default(session, remaining[0])


async def _make_default(session: AsyncSession, connection: ConfluenceConnection) -> None:
    """Exactly one default, cleared in one statement so the invariant cannot be
    left half-applied."""
    await session.execute(
        update(ConfluenceConnection)
        .where(ConfluenceConnection.id != connection.id)
        .values(is_default=False)
    )
    connection.is_default = True
    await session.flush()


async def _ensure_name_free(session: AsyncSession, name: str) -> None:
    result = await session.execute(
        select(ConfluenceConnection).where(ConfluenceConnection.name == name)
    )
    if result.scalar_one_or_none() is not None:
        raise ConflictError(
            ConfluenceEntity.CONNECTION, reason=f"a connection named {name!r} exists"
        )


async def _count(session: AsyncSession) -> int:
    result = await session.execute(select(ConfluenceConnection.id))
    return len(list(result.scalars()))


# --- env seeding (startup) ----------------------------------------------------


async def seed_from_env() -> None:
    """Turn an environment configuration into a real connection row, ONCE.

    Only when the table is empty, so an admin who deletes or renames the seeded row
    never has it silently reappear. Seeded rows are ordinary editable connections —
    fixing the URL without a redeploy is the point of the move to DB rows.
    """
    base_url = settings.confluence_base_url.strip()
    if not base_url:
        return
    pat = settings.confluence_pat.strip()
    user, password = settings.confluence_user.strip(), settings.confluence_password
    if pat:
        mode, username, credential = ConfluenceAuthMode.PAT, "", pat
    elif user and password:
        mode, username, credential = ConfluenceAuthMode.BASIC, user, password
    else:
        return
    async with SessionLocal() as session:
        if await _count(session) > 0:
            return
        await create_connection(
            session,
            ConnectionCreate(
                name=_seed_name(base_url),
                base_url=base_url,
                auth_mode=mode,
                username=username,
                credential=credential,
                verify_ssl=settings.confluence_verify_ssl,
                is_default=True,
            ),
            source=ConnectionSource.ENV,
        )
        await session.commit()
    logger.info(
        "confluenceimport: seeded a Confluence connection for %s from the environment",
        base_url,
    )


def _seed_name(base_url: str) -> str:
    host = base_url.split("://", 1)[-1].split("/", 1)[0]
    return host or "Confluence"
