"""Async wrappers over the synchronous client (spec 117).

Every REST call runs in `asyncio.to_thread` and takes a `ConfluenceCreds` value,
never the ORM row — the row belongs to a session on the event loop's thread.
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from . import connections
from .client import ConfluenceClient, ConfluenceUnavailable
from .schemas import ConnectionStatus, PageNode, SpaceRead
from .types import ConfluenceCreds


def _spaces(creds: ConfluenceCreds) -> list[SpaceRead]:
    with ConfluenceClient(creds) as client:
        return [
            SpaceRead(key=s.key, name=s.name, id=s.id, description=s.description)
            for s in client.spaces()
        ]


def _whoami(creds: ConfluenceCreds) -> str:
    with ConfluenceClient(creds) as client:
        raw = client.whoami()
    return raw.get("username") or raw.get("displayName") or ""


def _tree(creds: ConfluenceCreds, space_key: str) -> list[PageNode]:
    with ConfluenceClient(creds) as client:
        return [
            PageNode(
                id=p.id,
                title=p.title,
                parent_id=p.parent_id,
                space_key=p.space_key or space_key,
                position=p.position,
                version=p.version,
            )
            for p in client.space_pages(space_key)
        ]


async def check_connection(
    session: AsyncSession, connection_id: uuid.UUID | None = None
) -> ConnectionStatus:
    """Liveness for the settings banner. Never raises for "nothing configured" —
    that is a state the page must be able to render, not an error."""
    connection = await connections.default_connection(session) if connection_id is None \
        else await connections.get_connection(session, connection_id)
    if connection is None:
        return ConnectionStatus(configured=False)
    creds = connections.creds_of(connection)
    try:
        user = await asyncio.to_thread(_whoami, creds)
    except ConfluenceUnavailable as exc:
        return ConnectionStatus(
            configured=True, ok=False, detail=str(exc), connection_id=connection.id
        )
    return ConnectionStatus(
        configured=True, ok=True, connection_id=connection.id, user=user
    )


async def list_spaces(
    session: AsyncSession, connection_id: uuid.UUID | None = None
) -> list[SpaceRead]:
    connection = await connections.require_connection(session, connection_id)
    return await asyncio.to_thread(_spaces, connections.creds_of(connection))


async def space_tree(
    session: AsyncSession, space_key: str, connection_id: uuid.UUID | None = None
) -> list[PageNode]:
    """The remote tree, for the scope picker — flat, with `parent_id`, the same
    shape the SPA's own page tree consumes."""
    connection = await connections.require_connection(session, connection_id)
    return await asyncio.to_thread(_tree, connections.creds_of(connection), space_key)
