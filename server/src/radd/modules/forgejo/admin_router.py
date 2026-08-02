"""Connection + repository administration (spec 111).

Separate router from the webhook receiver on purpose: the receiver is
unauthenticated and verified by HMAC, everything here is admin-level and
verified by the permission engine. Mixing them in one file is how a
credential-bearing endpoint eventually inherits the wrong dependency.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import get_session
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser

from . import backfill, service
from .schemas import (
    ConnectionCreate,
    ConnectionRead,
    ConnectionTest,
    ConnectionUpdate,
    RepoCreate,
    RepoRead,
    RepoUpdate,
)

router = APIRouter(prefix="/forgejo", tags=["forgejo"])

Session = Annotated[AsyncSession, Depends(get_session)]


async def _read(session: AsyncSession, connection) -> ConnectionRead:
    return ConnectionRead(
        id=connection.id,
        name=connection.name,
        base_url=connection.base_url,
        active=connection.active,
        verify_ssl=connection.verify_ssl,
        has_token=bool(connection.api_token),
        has_secret=bool(connection.webhook_secret),
        repo_count=await service.repo_count(session, connection.id),
        created_at=connection.created_at,
    )


# --- connections ---


@router.post("/connections", response_model=ConnectionRead, status_code=201)
async def create_connection(
    data: ConnectionCreate, session: Session, user: CurrentUser
) -> ConnectionRead:
    await authz.require(session, user, authz.Permission.VCSCONN_CREATE)
    return await _read(session, await service.create_connection(session, data))


@router.get("/connections", response_model=list[ConnectionRead])
async def list_connections(session: Session, user: CurrentUser) -> list[ConnectionRead]:
    await authz.require(session, user, authz.Permission.GLOBAL_MANAGE)
    return [await _read(session, c) for c in await service.list_connections(session)]


@router.patch("/connections/{connection_id}", response_model=ConnectionRead)
async def update_connection(
    connection_id: uuid.UUID, data: ConnectionUpdate, session: Session, user: CurrentUser
) -> ConnectionRead:
    await authz.require(session, user, authz.Permission.VCSCONN_UPDATE)
    return await _read(session, await service.update_connection(session, connection_id, data))


@router.delete("/connections/{connection_id}", status_code=204)
async def delete_connection(
    connection_id: uuid.UUID, session: Session, user: CurrentUser
) -> None:
    await authz.require(session, user, authz.Permission.VCSCONN_DELETE)
    await service.delete_connection(session, connection_id)


@router.post("/connections/{connection_id}/test", response_model=ConnectionTest)
async def test_connection(
    connection_id: uuid.UUID, session: Session, user: CurrentUser
) -> ConnectionTest:
    """Call the host's /api/v1/version. Reports what went wrong rather than
    raising: "is this configured correctly" is the question, and a failure IS
    the answer."""
    await authz.require(session, user, authz.Permission.GLOBAL_MANAGE)
    connection = await service.get_connection(session, connection_id)
    if not connection.base_url:
        return ConnectionTest(ok=False, detail="no base URL set")
    headers = {"Authorization": f"token {connection.api_token}"} if connection.api_token else {}
    try:
        async with httpx.AsyncClient(verify=connection.verify_ssl, timeout=15) as client:
            response = await client.get(
                f"{connection.base_url}/api/v1/version", headers=headers
            )
        if response.status_code >= 400:
            return ConnectionTest(ok=False, detail=f"HTTP {response.status_code}")
        return ConnectionTest(ok=True, version=response.json().get("version", ""))
    except Exception as exc:  # network, TLS, DNS — all the same answer to the admin
        return ConnectionTest(ok=False, detail=f"{type(exc).__name__}: {exc}"[:200])


# --- repositories ---


@router.post("/repos", response_model=RepoRead, status_code=201)
async def create_repo(data: RepoCreate, session: Session, user: CurrentUser) -> RepoRead:
    await authz.require(session, user, authz.Permission.VCSCONN_CREATE)
    return RepoRead.model_validate(await service.create_repo(session, data))


@router.get("/repos", response_model=list[RepoRead])
async def list_repos(
    session: Session, user: CurrentUser, connection_id: uuid.UUID | None = None
) -> list[RepoRead]:
    await authz.require(session, user, authz.Permission.GLOBAL_MANAGE)
    return [RepoRead.model_validate(r) for r in await service.list_repos(session, connection_id)]


@router.patch("/repos/{repo_id}", response_model=RepoRead)
async def update_repo(
    repo_id: uuid.UUID, data: RepoUpdate, session: Session, user: CurrentUser
) -> RepoRead:
    await authz.require(session, user, authz.Permission.VCSCONN_UPDATE)
    return RepoRead.model_validate(await service.update_repo(session, repo_id, data))


@router.delete("/repos/{repo_id}", status_code=204)
async def delete_repo(repo_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
    await authz.require(session, user, authz.Permission.VCSCONN_DELETE)
    await service.delete_repo(session, repo_id)


__all__ = ["router", "settings"]


@router.post("/repos/{repo_id}/backfill")
async def backfill_repo(
    repo_id: uuid.UUID,
    session: Session,
    user: CurrentUser,
    max_commits: int | None = None,
) -> dict:
    """Walk the repository's existing branches, PRs and commits and link what the
    webhook never saw. Idempotent — the upsert seam dedups by external id."""
    await authz.require(session, user, authz.Permission.VCSCONN_UPDATE)
    repo = await service.get_repo(session, repo_id)
    connection = await service.get_connection(session, repo.connection_id)
    if not connection.api_token:
        raise HTTPException(
            status_code=422,
            detail="this connection has no API token; backfill reads the Forgejo API",
        )
    report = await backfill.run(session, connection, repo, max_commits=max_commits)
    repo.last_backfill_at = datetime.now(UTC).replace(tzinfo=None)
    await session.flush()
    return report.as_dict()
