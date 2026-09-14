"""Confluence import — connections and discovery (spec 117).

Instance-admin only: importing creates spaces, provisions users and writes
restrictions, and the connection speaks for a service account. No new permission
atoms — an importer is an admin tool, and inventing `confluenceimport.*` atoms
nobody grants is exactly the dead-atom problem spec 87 audited.

A 409 (not 403) means no connection exists: the caller is allowed, a piece of the
SETUP is missing.

Route order matters. Starlette matches in DECLARATION order, so every literal
segment here is declared before any `/{id}` route that could swallow it — a
literal written afterwards registers, appears at /docs, and answers a 422 about
parsing the word as a UUID (RADD-761). `tests/test_route_shadowing.py` asserts it
for the whole app.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.exceptions import ForbiddenError
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser
from radd.modules.auth.models import User

from . import connections, service
from .schemas import (
    ConnectionCreate,
    ConnectionRead,
    ConnectionStatus,
    ConnectionUpdate,
    PageNode,
    SpaceRead,
)

router = APIRouter(prefix="/confluence", tags=["confluence import"])

Session = Annotated[AsyncSession, Depends(get_session)]


def _admin(actor: User) -> None:
    if not authz.is_instance_admin(actor):
        raise ForbiddenError("Confluence import requires an instance admin")


# --- connections --------------------------------------------------------------


@router.get("/connections", response_model=list[ConnectionRead])
async def list_connections(session: Session, user: CurrentUser) -> list[ConnectionRead]:
    _admin(user)
    return [
        ConnectionRead.model_validate(c) for c in await connections.list_connections(session)
    ]


@router.post("/connections", response_model=ConnectionRead, status_code=201)
async def create_connection(
    data: ConnectionCreate, session: Session, user: CurrentUser
) -> ConnectionRead:
    _admin(user)
    connection = await connections.create_connection(session, data, actor_id=user.id)
    await session.commit()
    return ConnectionRead.model_validate(connection)


@router.patch("/connections/{connection_id}", response_model=ConnectionRead)
async def update_connection(
    connection_id: uuid.UUID, data: ConnectionUpdate, session: Session, user: CurrentUser
) -> ConnectionRead:
    _admin(user)
    connection = await connections.update_connection(
        session, connection_id, data, actor_id=user.id
    )
    await session.commit()
    return ConnectionRead.model_validate(connection)


@router.delete("/connections/{connection_id}", status_code=204)
async def delete_connection(
    connection_id: uuid.UUID, session: Session, user: CurrentUser
) -> None:
    _admin(user)
    await connections.delete_connection(session, connection_id, actor_id=user.id)
    await session.commit()


@router.post("/connections/{connection_id}/test", response_model=ConnectionStatus)
async def test_connection(
    connection_id: uuid.UUID, session: Session, user: CurrentUser
) -> ConnectionStatus:
    _admin(user)
    return await service.check_connection(session, connection_id)


# --- discovery ----------------------------------------------------------------


@router.get("/status", response_model=ConnectionStatus)
async def status(session: Session, user: CurrentUser) -> ConnectionStatus:
    """Readable with nothing configured — `configured: false` is an answer, so the
    settings page renders before setup rather than showing an error."""
    _admin(user)
    return await service.check_connection(session)


@router.get("/spaces", response_model=list[SpaceRead])
async def list_spaces(
    session: Session, user: CurrentUser, connection_id: uuid.UUID | None = None
) -> list[SpaceRead]:
    _admin(user)
    return await service.list_spaces(session, connection_id)


@router.get("/spaces/{space_key}/tree", response_model=list[PageNode])
async def space_tree(
    space_key: str,
    session: Session,
    user: CurrentUser,
    connection_id: uuid.UUID | None = None,
    parent_id: str = "",
) -> list[PageNode]:
    """ONE level of the remote tree — the space's roots, or one page's children.

    Lazy on purpose: fetching a real 6000-page space up front took 61 requests and
    over two minutes, which is a hang rather than a picker.
    """
    _admin(user)
    return await service.space_tree(session, space_key, connection_id, parent_id)
