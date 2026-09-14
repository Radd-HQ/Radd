"""Jira import wizard — HTTP surface (specs 90, 100).

Instance-admin only: importing rewrites projects and provisions users, and the
connection speaks for a service account. A 409 (not 403) means no Jira connection
exists — the caller is allowed, a piece of the setup is missing — the same
convention the ldap module uses.

Spec 100 added `/jira/connections` CRUD: which Jira to talk to is a database row
an admin manages here, not an environment variable needing a redeploy. Every
Jira-touching endpoint takes an optional `connection_id` and falls back to the
default one. Credentials are never returned — reads expose `has_credential`.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.exceptions import ConflictError, ForbiddenError
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser
from radd.modules.auth.models import User

from . import client, connections, service, snapshot
from .models import JiraConnection, JiraSnapshot
from .schemas import (
    InferredFieldRead,
    JiraConnectionCreate,
    JiraConnectionRead,
    JiraConnectionStatus,
    JiraConnectionUpdate,
    JiraPreviewRequest,
    JiraPreviewResponse,
    JiraProjectRead,
    SnapshotRead,
    SnapshotStart,
)
from .types import JiraEntity

router = APIRouter(prefix="/jira", tags=["jira import"])

Session = Annotated[AsyncSession, Depends(get_session)]


def _require_instance_admin(actor: User) -> None:
    if not authz.is_instance_admin(actor):
        raise ForbiddenError("Jira import requires an instance admin")


# --- connections (spec 100) ---------------------------------------------------


@router.get("/connections", response_model=list[JiraConnectionRead])
async def list_connections(session: Session, user: CurrentUser) -> list[JiraConnectionRead]:
    _require_instance_admin(user)
    return [
        JiraConnectionRead.model_validate(c) for c in await connections.list_connections(session)
    ]


@router.post("/connections", response_model=JiraConnectionRead, status_code=201)
async def create_connection(
    data: JiraConnectionCreate, session: Session, user: CurrentUser
) -> JiraConnectionRead:
    _require_instance_admin(user)
    connection = await connections.create_connection(session, data, actor_id=user.id)
    await session.commit()
    return JiraConnectionRead.model_validate(connection)


@router.patch("/connections/{connection_id}", response_model=JiraConnectionRead)
async def update_connection(
    connection_id: uuid.UUID, data: JiraConnectionUpdate, session: Session, user: CurrentUser
) -> JiraConnectionRead:
    _require_instance_admin(user)
    connection = await connections.update_connection(
        session, connection_id, data, actor_id=user.id
    )
    await session.commit()
    return JiraConnectionRead.model_validate(connection)


@router.delete("/connections/{connection_id}", status_code=204)
async def delete_connection(
    connection_id: uuid.UUID, session: Session, user: CurrentUser
) -> None:
    _require_instance_admin(user)
    await connections.delete_connection(session, connection_id, actor_id=user.id)
    await session.commit()


@router.post("/connections/{connection_id}/test", response_model=JiraConnectionStatus)
async def test_connection(
    connection_id: uuid.UUID, session: Session, user: CurrentUser
) -> JiraConnectionStatus:
    """Try the credentials against /myself. Never 500s — a stale token is a result
    to render next to the row, not an error page."""
    _require_instance_admin(user)
    connection = await connections.get_connection(session, connection_id)
    return await _status_of(connection)


@router.get("/status", response_model=JiraConnectionStatus)
async def jira_status(session: Session, user: CurrentUser) -> JiraConnectionStatus:
    """Is the DEFAULT connection live? Readable with none configured — the wizard
    renders "add a connection" from `configured: false`."""
    _require_instance_admin(user)
    connection = await connections.default_connection(session)
    if connection is None:
        return JiraConnectionStatus(configured=False, ok=False)
    return await _status_of(connection)


async def _status_of(connection: JiraConnection) -> JiraConnectionStatus:
    creds = connections.creds_of(connection)
    ok, account, error = await service.check_connection(creds)
    return JiraConnectionStatus(
        configured=True,
        ok=ok,
        account=account,
        auth_mode=creds.auth_mode.value,
        error=error,
        connection_id=connection.id,
        connection_name=connection.name,
    )


@router.get("/projects", response_model=list[JiraProjectRead])
async def jira_projects(
    session: Session, user: CurrentUser, connection_id: uuid.UUID | None = None
) -> list[JiraProjectRead]:
    """Every Jira project the service account can see — the wizard's project picker."""
    _require_instance_admin(user)
    connection = await connections.require_connection(session, connection_id)
    try:
        projects = await service.list_projects(connections.creds_of(connection))
    except client.JiraUnavailable as exc:
        raise ConflictError(JiraEntity.JIRA, reason=str(exc)) from exc
    return [JiraProjectRead(key=p.key, name=p.name, id=p.id, project_type=p.project_type) for p in projects]


@router.post("/preview", response_model=JiraPreviewResponse)
async def jira_preview(
    data: JiraPreviewRequest, session: Session, user: CurrentUser
) -> JiraPreviewResponse:
    """Load a JQL slice and infer the inbound schema — the 'once the query is
    loaded, create an inbound schema' step. A bad JQL is a 422 (ValueError), an
    unreachable Jira a 409."""
    _require_instance_admin(user)
    connection = await connections.require_connection(session, data.connection_id)
    try:
        total, fields = await service.preview(
            connections.creds_of(connection), data.jql, data.sample_size, data.project_key
        )
    except client.JiraUnavailable as exc:
        raise ConflictError(JiraEntity.JIRA, reason=str(exc)) from exc
    return JiraPreviewResponse(
        total=total,
        sampled=min(total, data.sample_size),
        fields=[
            InferredFieldRead(
                jira_id=f.jira_id,
                name=f.name,
                inferred_type=f.inferred_type,
                populated=f.populated,
                sample_count=f.sample_count,
                populate_rate=f.populate_rate,
                is_builtin=f.is_builtin,
                distinct_count=f.distinct_count,
                dominant_ratio=f.dominant_ratio,
                band=f.band,
                band_reason=f.band_reason,
                schema_key=f.schema_key,
                samples=f.samples,
                distinct_values=f.distinct_values,
            )
            for f in fields
        ],
    )


# --- snapshots (spec 100) -----------------------------------------------------


@router.get("/snapshots", response_model=list[SnapshotRead])
async def list_snapshots(session: Session, user: CurrentUser) -> list[SnapshotRead]:
    """Cached downloads, newest first — with their size, so an admin can see what
    each one costs and delete the ones they are done with."""
    _require_instance_admin(user)
    return [SnapshotRead.model_validate(s) for s in await snapshot.service.list_snapshots(session)]


@router.post("/snapshots", response_model=SnapshotRead, status_code=201)
async def start_snapshot(
    data: SnapshotStart, session: Session, user: CurrentUser
) -> SnapshotRead:
    """Download a JQL result set into the cache. Returns immediately; poll
    GET /jira/snapshots/{id} for live progress."""
    _require_instance_admin(user)
    connection = await connections.require_connection(session, data.connection_id)
    row = JiraSnapshot(
        connection_id=connection.id,
        actor_id=user.id,
        name=data.name.strip() or f"{data.jira_project_key} · {_stamp()}",
        jira_project_key=data.jira_project_key.upper(),
        jql=data.jql,
        include_attachments=data.include_attachments,
        include_history=data.include_history,
    )
    session.add(row)
    await session.commit()
    snapshot.download.start(row.id)  # fire-and-forget; the row tracks it
    return SnapshotRead.model_validate(row)


@router.get("/snapshots/{snapshot_id}", response_model=SnapshotRead)
async def get_snapshot(
    snapshot_id: uuid.UUID, session: Session, user: CurrentUser
) -> SnapshotRead:
    """Live progress of one download — the UI polls this."""
    _require_instance_admin(user)
    return SnapshotRead.model_validate(await snapshot.service.get_snapshot(session, snapshot_id))


@router.post("/snapshots/{snapshot_id}/cancel", response_model=SnapshotRead)
async def cancel_snapshot(
    snapshot_id: uuid.UUID, session: Session, user: CurrentUser
) -> SnapshotRead:
    """Stop a running download. Cooperative — it halts on a page boundary and
    keeps everything already cached."""
    _require_instance_admin(user)
    row = await snapshot.service.request_cancel(session, snapshot_id)
    await session.commit()
    return SnapshotRead.model_validate(row)


@router.delete("/snapshots/{snapshot_id}", status_code=204)
async def delete_snapshot(
    snapshot_id: uuid.UUID, session: Session, user: CurrentUser
) -> None:
    """Erase a cached download and its attachment blobs. 409 while it is running."""
    _require_instance_admin(user)
    await snapshot.service.delete_snapshot(session, snapshot_id)
    await session.commit()


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
