"""A connector's administration routes (`/<provider>/connections`, `/<provider>/repos`),
built once for every connector from its store (RADD-1435). The connector mounts the
router, so disabling the connector unmounts its routes.

Separate from the webhook receiver on purpose: the receiver is unauthenticated and
verified by the host's credential; everything here is admin-level and verified by
the permission engine (the `vcsconn.*` atoms)."""

import uuid
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser

from ..types import ConnectorSetting
from .schemas import (
    ConnectionRead,
    ConnectionTest,
    ConnectionUpdate,
    RepoCreate,
    RepoRead,
    RepoUpdate,
)
from .spec import ConnectorSpec
from .store import ConnectorStore

Session = Annotated[AsyncSession, Depends(get_session)]


async def probe_connection(spec: ConnectorSpec, connection: Any) -> ConnectionTest:
    """One request to the host's API. Reports what went wrong rather than raising:
    "is this configured correctly" is the question, and a failure IS the answer."""
    probe = spec.probe(connection)
    if probe is None:
        return ConnectionTest(ok=False, detail="no base URL set")
    try:
        async with httpx.AsyncClient(
            verify=connection.verify_ssl, timeout=spec.setting(ConnectorSetting.HTTP_TIMEOUT)
        ) as client:
            response = await client.get(probe.url, headers=connection.api_headers)
        if response.status_code >= 400:
            return ConnectionTest(ok=False, detail=f"HTTP {response.status_code}")
        return ConnectionTest(ok=True, version=probe.label(response.json()))
    except Exception as exc:  # network, TLS, DNS — all the same answer to the admin
        return ConnectionTest(ok=False, detail=f"{type(exc).__name__}: {exc}"[:200])


def admin_router(store: ConnectorStore) -> APIRouter:
    spec = store.spec
    provider = spec.provider.value
    router = APIRouter(prefix=f"/{provider}", tags=[provider])
    ConnectionCreate = store.connection_create

    async def _read(session: AsyncSession, connection) -> ConnectionRead:
        return ConnectionRead(
            id=connection.id,
            name=connection.name,
            base_url=connection.base_url,
            active=connection.active,
            verify_ssl=connection.verify_ssl,
            has_token=bool(connection.api_token),
            has_secret=bool(connection.webhook_secret),
            repo_count=await store.repo_count(session, connection.id),
            created_at=connection.created_at,
        )

    # --- connections ---

    @router.post("/connections", response_model=ConnectionRead, status_code=201)
    async def create_connection(data: ConnectionCreate, session: Session, user: CurrentUser) -> ConnectionRead:
        await authz.require(session, user, authz.Permission.VCSCONN_CREATE)
        return await _read(session, await store.create_connection(session, data, actor_id=user.id))

    @router.get("/connections", response_model=list[ConnectionRead])
    async def list_connections(session: Session, user: CurrentUser) -> list[ConnectionRead]:
        await authz.require(session, user, authz.Permission.GLOBAL_MANAGE)
        return [await _read(session, connection) for connection in await store.list_connections(session)]

    @router.patch("/connections/{connection_id}", response_model=ConnectionRead)
    async def update_connection(
        connection_id: uuid.UUID, data: ConnectionUpdate, session: Session, user: CurrentUser
    ) -> ConnectionRead:
        await authz.require(session, user, authz.Permission.VCSCONN_UPDATE)
        return await _read(session, await store.update_connection(session, connection_id, data, actor_id=user.id))

    @router.delete("/connections/{connection_id}", status_code=204)
    async def delete_connection(connection_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
        await authz.require(session, user, authz.Permission.VCSCONN_DELETE)
        await store.delete_connection(session, connection_id, actor_id=user.id)

    @router.post("/connections/{connection_id}/test", response_model=ConnectionTest)
    async def test_connection(connection_id: uuid.UUID, session: Session, user: CurrentUser) -> ConnectionTest:
        await authz.require(session, user, authz.Permission.GLOBAL_MANAGE)
        return await probe_connection(spec, await store.get_connection(session, connection_id))

    # --- repositories ---

    @router.post("/repos", response_model=RepoRead, status_code=201)
    async def create_repo(data: RepoCreate, session: Session, user: CurrentUser) -> RepoRead:
        await authz.require(session, user, authz.Permission.VCSCONN_CREATE)
        return RepoRead.model_validate(await store.create_repo(session, data, actor_id=user.id))

    @router.get("/repos", response_model=list[RepoRead])
    async def list_repos(session: Session, user: CurrentUser, connection_id: uuid.UUID | None = None) -> list[RepoRead]:
        await authz.require(session, user, authz.Permission.GLOBAL_MANAGE)
        return [RepoRead.model_validate(repo) for repo in await store.list_repos(session, connection_id)]

    @router.patch("/repos/{repo_id}", response_model=RepoRead)
    async def update_repo(repo_id: uuid.UUID, data: RepoUpdate, session: Session, user: CurrentUser) -> RepoRead:
        await authz.require(session, user, authz.Permission.VCSCONN_UPDATE)
        return RepoRead.model_validate(await store.update_repo(session, repo_id, data, actor_id=user.id))

    @router.delete("/repos/{repo_id}", status_code=204)
    async def delete_repo(repo_id: uuid.UUID, session: Session, user: CurrentUser) -> None:
        await authz.require(session, user, authz.Permission.VCSCONN_DELETE)
        await store.delete_repo(session, repo_id, actor_id=user.id)

    @router.post("/repos/{repo_id}/backfill")
    async def backfill_repo(
        repo_id: uuid.UUID, session: Session, user: CurrentUser, max_commits: int | None = None
    ) -> dict:
        """Walk the repository's branches, merge/pull requests and commits and link
        what the webhook never saw. Idempotent — the upsert seam dedups by external id."""
        await authz.require(session, user, authz.Permission.VCSCONN_UPDATE)
        repo = await store.get_repo(session, repo_id)
        connection = await store.get_connection(session, repo.connection_id)
        if not connection.api_token:
            raise HTTPException(
                status_code=422,
                detail=f"this connection has no API token; backfill reads the {spec.wording.title} API",
            )
        return (await store.backfill(session, connection, repo, max_commits=max_commits)).as_dict()

    return router
