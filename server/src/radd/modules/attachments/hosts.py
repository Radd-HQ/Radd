"""Storage host registry (spec 102) — CRUD, the default invariant, env seeding.

The jiraimport-connections pattern throughout: env config seeds ONE host row
when the table is empty (a fresh install always gets a working default), rows
are ordinary and editable afterwards, secrets are redacted on read and an empty
secret on update means "keep". A process-local snapshot of the default host
serves the sync capability check.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import SessionLocal
from radd.snapshot import Snapshot
from radd.exceptions import ConflictError, NotFoundError

from .models import Attachment, StorageHost
from .schemas import StorageHostCreate, StorageHostUpdate
from .types import AttachmentEntity, DeliveryMode, StorageHostSource, StorageHostType

logger = logging.getLogger(__name__)

# An empty credential on update keeps the stored one (reads are redacted).
UNCHANGED_CREDENTIAL = ""

# Other modules storing bytes through the blob API register a counter so a host
# they still reference cannot be deleted (jiraimport: snapshot blobs).
UseCheck = Callable[[AsyncSession, uuid.UUID], Awaitable[int]]
_use_checks: list[UseCheck] = []


def register_use_check(check: UseCheck) -> None:
    _use_checks.append(check)


# --- reads --------------------------------------------------------------------


async def list_hosts(session: AsyncSession) -> list[StorageHost]:
    result = await session.execute(
        select(StorageHost).order_by(StorageHost.is_default.desc(), StorageHost.name)
    )
    return list(result.scalars())


async def get_host(session: AsyncSession, host_id: uuid.UUID) -> StorageHost:
    host = await session.get(StorageHost, host_id)
    if host is None:
        raise NotFoundError(AttachmentEntity.HOST, host_id)
    return host


async def require_default(session: AsyncSession) -> StorageHost:
    """The default host. 409 (not 404) when none exists: the caller is allowed,
    a piece of the deploy is missing — the ldap/jiraimport convention."""
    result = await session.execute(select(StorageHost).where(StorageHost.is_default))
    host = result.scalar_one_or_none()
    if host is None:
        raise ConflictError(
            AttachmentEntity.HOST,
            reason="no default storage host is configured — add one under Settings → Storage",
        )
    return host


async def selectable_hosts(session: AsyncSession) -> list[StorageHost]:
    result = await session.execute(
        select(StorageHost).where(StorageHost.user_selectable).order_by(StorageHost.name)
    )
    return list(result.scalars())


async def name_map(session: AsyncSession) -> dict[uuid.UUID, str]:
    """{host_id: name} — hosts are few; the read endpoints label attachments."""
    result = await session.execute(select(StorageHost.id, StorageHost.name))
    return dict(result.all())


async def attachment_counts(session: AsyncSession) -> dict[uuid.UUID, tuple[int, int]]:
    """{host_id: (attachment_count, total_bytes)} in one grouped query."""
    result = await session.execute(
        select(
            Attachment.storage_host_id,
            func.count(Attachment.id),
            func.coalesce(func.sum(Attachment.size_bytes), 0),
        ).group_by(Attachment.storage_host_id)
    )
    return {host_id: (count, int(total)) for host_id, count, total in result.all()}


def backup_roots(hosts: list[StorageHost]) -> list[tuple[str, Path]]:
    """(host name, root) for every filesystem host — what a backup can include.
    S3-hosted bytes stay outside backups (documented in docs/deploy.md)."""
    return [
        (host.name, Path(host.root_dir or settings.attachments_dir))
        for host in hosts
        if host.host_type == StorageHostType.FILESYSTEM.value
    ]


# --- writes -------------------------------------------------------------------


def _validate(host_type: StorageHostType, fields: dict) -> None:
    if host_type is StorageHostType.FILESYSTEM:
        if fields.get("delivery_mode") == DeliveryMode.PRESIGNED.value:
            raise ConflictError(
                AttachmentEntity.HOST, reason="a filesystem host can only deliver via proxy"
            )
    elif not fields.get("endpoint") or not fields.get("bucket"):
        raise ConflictError(
            AttachmentEntity.HOST, reason="an s3 host needs an endpoint and a bucket"
        )


async def create_host(
    session: AsyncSession,
    data: StorageHostCreate,
    *,
    source: StorageHostSource = StorageHostSource.USER,
) -> StorageHost:
    await _ensure_name_free(session, data.name)
    fields = data.model_dump()
    _validate(data.host_type, fields)
    host = StorageHost(
        name=data.name,
        host_type=data.host_type.value,
        endpoint=data.endpoint,
        access_key=data.access_key,
        secret_key=data.secret_key,
        bucket=data.bucket,
        region=data.region,
        secure=data.secure,
        root_dir=data.root_dir,
        delivery_mode=data.delivery_mode.value,
        presign_expiry_seconds=data.presign_expiry_seconds,
        user_selectable=data.user_selectable,
        source=source.value,
    )
    session.add(host)
    await session.flush()
    # First host in is the default, so a single-host deploy is complete at once.
    if data.is_default or await _count(session) == 1:
        await make_default(session, host)
    return host


async def update_host(
    session: AsyncSession, host_id: uuid.UUID, data: StorageHostUpdate
) -> StorageHost:
    host = await get_host(session, host_id)
    fields = data.model_dump(exclude_unset=True)
    if "name" in fields and fields["name"] != host.name:
        await _ensure_name_free(session, fields["name"])
        host.name = fields["name"]
    for column in ("endpoint", "bucket", "region", "root_dir"):
        if column in fields:
            setattr(host, column, fields[column])
    if "access_key" in fields:
        host.access_key = fields["access_key"]
    # Empty secret = keep the stored one (the read shape is redacted).
    if fields.get("secret_key"):
        host.secret_key = fields["secret_key"]
    if "secure" in fields:
        host.secure = fields["secure"]
    if "delivery_mode" in fields:
        host.delivery_mode = DeliveryMode(fields["delivery_mode"]).value
    if "presign_expiry_seconds" in fields:
        host.presign_expiry_seconds = fields["presign_expiry_seconds"]
    if "user_selectable" in fields:
        host.user_selectable = fields["user_selectable"]
    _validate(StorageHostType(host.host_type), _column_state(host))
    await session.flush()
    if fields.get("is_default"):
        await make_default(session, host)
    await refresh_default_snapshot(session)
    return host


def _column_state(host: StorageHost) -> dict:
    return {
        "endpoint": host.endpoint,
        "bucket": host.bucket,
        "delivery_mode": host.delivery_mode,
    }


async def delete_host(session: AsyncSession, host_id: uuid.UUID) -> None:
    host = await get_host(session, host_id)
    used = await session.scalar(
        select(func.count(Attachment.id)).where(Attachment.storage_host_id == host_id)
    )
    if used:
        raise ConflictError(
            AttachmentEntity.HOST,
            reason=f"{used} attachments live on this host — move them first",
        )
    for check in _use_checks:
        held = await check(session, host_id)
        if held:
            raise ConflictError(
                AttachmentEntity.HOST,
                reason=f"{held} stored blobs still reference this host",
            )
    was_default = host.is_default
    await session.delete(host)
    await session.flush()
    if was_default:  # promote another so a multi-host deploy keeps a default
        remaining = await list_hosts(session)
        if remaining:
            await make_default(session, remaining[0])
    await refresh_default_snapshot(session)


async def make_default(session: AsyncSession, host: StorageHost) -> None:
    """Exactly one default, cleared in one statement (the connections idiom)."""
    await session.execute(
        update(StorageHost).where(StorageHost.id != host.id).values(is_default=False)
    )
    host.is_default = True
    await session.flush()
    await refresh_default_snapshot(session)


async def _ensure_name_free(session: AsyncSession, name: str) -> None:
    result = await session.execute(select(StorageHost).where(StorageHost.name == name))
    if result.scalar_one_or_none() is not None:
        raise ConflictError(AttachmentEntity.HOST, reason=f"a host named {name!r} exists")


async def _count(session: AsyncSession) -> int:
    return (await session.scalar(select(func.count(StorageHost.id)))) or 0


# --- capability snapshot ------------------------------------------------------

# CapabilitySpec.check is sync; this mirrors the ai registry's role snapshot —
# write-through + TTL'd (RADD-899) so extra web replicas converge.


def _default_of(host: "StorageHost | None") -> dict[str, str]:
    if host is None:
        return {}
    return {"type": host.host_type, "name": host.name, "root_dir": host.root_dir}


async def _load_default_snapshot() -> dict[str, str]:
    from radd.db import SessionLocal

    async with SessionLocal() as session:
        result = await session.execute(select(StorageHost).where(StorageHost.is_default))
        return _default_of(result.scalar_one_or_none())


_default_snapshot: Snapshot[dict[str, str]] = Snapshot(
    "attachments.default-host", _load_default_snapshot, initial={}
)


def default_snapshot() -> dict[str, str]:
    return dict(_default_snapshot.get())


async def refresh_default_snapshot(session: AsyncSession) -> None:
    result = await session.execute(select(StorageHost).where(StorageHost.is_default))
    _default_snapshot.set(_default_of(result.scalar_one_or_none()))


# --- env seeding (startup) ----------------------------------------------------


def seed_values() -> StorageHostCreate:
    """The host the environment describes (shared by startup seeding; the spec-102
    migration inlines the same logic for installs with existing attachments)."""
    if settings.attachment_storage == StorageHostType.S3.value:
        return StorageHostCreate(
            name=settings.s3_bucket or "s3",
            host_type=StorageHostType.S3,
            endpoint=settings.s3_endpoint,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            bucket=settings.s3_bucket,
            secure=settings.s3_secure,
            # Presigned redirect is exactly what the spec-33 S3 path always did.
            delivery_mode=DeliveryMode.PRESIGNED,
            is_default=True,
        )
    return StorageHostCreate(
        name="Local disk",
        host_type=StorageHostType.FILESYSTEM,
        root_dir=settings.attachments_dir,
        delivery_mode=DeliveryMode.PROXY,
        is_default=True,
    )


async def seed_from_env() -> None:
    """Create the environment's host ONCE (empty table only), then refresh the
    capability snapshot. Every install ends up with a default host."""
    async with SessionLocal() as session:
        if await _count(session) == 0:
            await create_host(session, seed_values(), source=StorageHostSource.ENV)
            await session.commit()
            logger.info("attachments: seeded a storage host from the environment")
        await refresh_default_snapshot(session)
