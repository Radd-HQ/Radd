"""Settings → Storage admin API (spec 102): storage hosts.

Instance-admin only (the ai admin-router idiom). Reads redact the secret
(`has_secret_key`) and carry usage counts from ONE grouped query; an empty
secret on update means "keep the stored one" (handled in the service). Health
is a live probe against the host — never stored, and failures come back as
data (the admin is diagnosing config), never a 500.
"""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.exceptions import ForbiddenError
from radd.modules.auth import authz
from radd.modules.auth.deps import CurrentUser
from radd.modules.auth.models import User

from . import clients, hosts, movejob
from .models import StorageHost
from .routing import store as routing_store
from .schemas import (
    StorageHostCreate,
    StorageHostRead,
    StorageHostUpdate,
    StorageRuleCreate,
    StorageRuleOrder,
    StorageRuleRead,
    StorageRuleUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/storage", tags=["storage admin"])

Session = Annotated[AsyncSession, Depends(get_session)]


def _require_instance_admin(actor: User) -> None:
    if not authz.is_instance_admin(actor):
        raise ForbiddenError("storage settings require an instance admin")


def _read(host: StorageHost, counts: dict[uuid.UUID, tuple[int, int]]) -> StorageHostRead:
    count, total = counts.get(host.id, (0, 0))
    return StorageHostRead.model_validate(host).model_copy(
        update={"attachment_count": count, "total_bytes": total}
    )


@router.get("/hosts", response_model=list[StorageHostRead])
async def list_storage_hosts(session: Session, user: CurrentUser) -> list[StorageHostRead]:
    _require_instance_admin(user)
    counts = await hosts.attachment_counts(session)
    return [_read(host, counts) for host in await hosts.list_hosts(session)]


@router.post("/hosts", response_model=StorageHostRead, status_code=201)
async def create_storage_host(
    data: StorageHostCreate, session: Session, user: CurrentUser
) -> StorageHostRead:
    _require_instance_admin(user)
    host = await hosts.create_host(session, data, actor_id=user.id)
    # create_host only refreshes the capability snapshot when it promotes a
    # default — cover the other path so the Server pill never lags this write.
    await hosts.refresh_default_snapshot(session)
    # Best-effort eager readiness (make the bucket/dir now); a failure is the
    # health endpoint's story, not a failed create.
    try:
        await clients.client_for(host).ensure_ready()
    except Exception:  # noqa: BLE001 — any SDK/OS failure surfaces via /health
        logger.warning("attachments: new host %r is not ready", host.name, exc_info=True)
    return _read(host, {})


@router.patch("/hosts/{host_id}", response_model=StorageHostRead)
async def update_storage_host(
    host_id: uuid.UUID, data: StorageHostUpdate, session: Session, user: CurrentUser
) -> StorageHostRead:
    _require_instance_admin(user)
    host = await hosts.update_host(session, host_id, data, actor_id=user.id)
    return _read(host, await hosts.attachment_counts(session))


@router.delete("/hosts/{host_id}", status_code=204)
async def delete_storage_host(host_id: uuid.UUID, session: Session, user: CurrentUser) -> Response:
    """409 (with the reason) while attachments or blobs still live on the host,
    or when it's the only host left holding the default."""
    _require_instance_admin(user)
    await hosts.delete_host(session, host_id, actor_id=user.id)
    return Response(status_code=204)


@router.post("/hosts/{host_id}/default", response_model=StorageHostRead)
async def make_storage_host_default(
    host_id: uuid.UUID, session: Session, user: CurrentUser
) -> StorageHostRead:
    _require_instance_admin(user)
    host = await hosts.get_host(session, host_id)
    await hosts.make_default(session, host, actor_id=user.id)
    return _read(host, await hosts.attachment_counts(session))


class HostHealthRead(BaseModel):
    ok: bool
    detail: str = ""


@router.get("/hosts/{host_id}/health", response_model=HostHealthRead)
async def storage_host_health(
    host_id: uuid.UUID, session: Session, user: CurrentUser
) -> HostHealthRead:
    """Live probe: write+delete for filesystem, bucket_exists for S3. Anything
    unexpected is the answer, not a 500."""
    _require_instance_admin(user)
    host = await hosts.get_host(session, host_id)
    try:
        health = await clients.client_for(host).health()
    except Exception as exc:  # noqa: BLE001 — a broken host config must render, not 500
        return HostHealthRead(ok=False, detail=str(exc))
    return HostHealthRead(ok=health.ok, detail=health.detail)


# --- move jobs (spec 102 §move) ------------------------------------------------


class MoveJobCreate(BaseModel):
    target_host_id: uuid.UUID


class MoveJobRead(BaseModel):
    id: uuid.UUID
    source_host_id: uuid.UUID
    target_host_id: uuid.UUID
    state: str
    total: int
    moved: int
    failed: int
    problems: list

    model_config = {"from_attributes": True}


@router.post("/hosts/{host_id}/move", response_model=MoveJobRead, status_code=201)
async def move_host_attachments(
    host_id: uuid.UUID, data: MoveJobCreate, session: Session, user: CurrentUser
) -> MoveJobRead:
    """Start a background move of every attachment on this host to the target
    (copy -> verify -> repoint -> best-effort source delete, per file)."""
    _require_instance_admin(user)
    job = await movejob.create_job(
        session, source_host_id=host_id, target_host_id=data.target_host_id, actor_id=user.id
    )
    await session.commit()  # the task reads with its own sessions
    movejob.start(job.id)
    return MoveJobRead.model_validate(job)


@router.get("/move-jobs", response_model=list[MoveJobRead])
async def list_move_jobs(session: Session, user: CurrentUser) -> list[MoveJobRead]:
    _require_instance_admin(user)
    return [MoveJobRead.model_validate(j) for j in await movejob.list_jobs(session)]


@router.get("/move-jobs/{job_id}", response_model=MoveJobRead)
async def get_move_job(job_id: uuid.UUID, session: Session, user: CurrentUser) -> MoveJobRead:
    _require_instance_admin(user)
    return MoveJobRead.model_validate(await movejob.get_job(session, job_id))


# --- routing rules (spec 102 §routing) -----------------------------------------


@router.get("/rules", response_model=list[StorageRuleRead])
async def list_rules(session: Session, user: CurrentUser) -> list[StorageRuleRead]:
    _require_instance_admin(user)
    return [StorageRuleRead.model_validate(r) for r in await routing_store.ordered_rules(session)]


@router.post("/rules", response_model=StorageRuleRead, status_code=201)
async def create_rule(data: StorageRuleCreate, session: Session, user: CurrentUser) -> StorageRuleRead:
    _require_instance_admin(user)
    rule = await routing_store.create_rule(
        session,
        name=data.name,
        rule_type=data.rule_type,
        config=data.config,
        enabled=data.enabled,
        actor_id=user.id,
    )
    return StorageRuleRead.model_validate(rule)


@router.patch("/rules/{rule_id}", response_model=StorageRuleRead)
async def update_rule(
    rule_id: uuid.UUID, data: StorageRuleUpdate, session: Session, user: CurrentUser
) -> StorageRuleRead:
    _require_instance_admin(user)
    fields = data.model_dump(exclude_unset=True)
    rule = await routing_store.update_rule(
        session,
        rule_id,
        name=fields.get("name"),
        config=fields.get("config"),
        enabled=fields.get("enabled"),
        actor_id=user.id,
    )
    return StorageRuleRead.model_validate(rule)


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule(rule_id: uuid.UUID, session: Session, user: CurrentUser) -> Response:
    _require_instance_admin(user)
    await routing_store.delete_rule(session, rule_id, actor_id=user.id)
    return Response(status_code=204)


@router.put("/rules/order", response_model=list[StorageRuleRead])
async def reorder_rules(
    data: StorageRuleOrder, session: Session, user: CurrentUser
) -> list[StorageRuleRead]:
    _require_instance_admin(user)
    rules = await routing_store.reorder(session, data.ids, actor_id=user.id)
    return [StorageRuleRead.model_validate(r) for r in rules]
