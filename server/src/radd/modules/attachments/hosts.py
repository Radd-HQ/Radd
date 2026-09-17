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

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.db import SessionLocal
from radd.snapshot import Snapshot
from radd.exceptions import ConflictError, NotFoundError
from radd.kernel import changes
from radd.modules.events import service as events

from .models import Attachment, StorageHost
from .schemas import StorageHostCreate, StorageHostUpdate
from .types import (
    AttachmentEntity,
    AttachmentEvent,
    DeliveryMode,
    StorageHostSource,
    StorageHostType,
)

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


# --- writes -------------------------------------------------------------------


def _validate(host_type: StorageHostType, fields: dict) -> None:
    if host_type is StorageHostType.FILESYSTEM:
        if fields.get("delivery_mode") == DeliveryMode.PRESIGNED.value:
            raise ConflictError(
                AttachmentEntity.HOST, reason="a filesystem host can only deliver via proxy"
            )
        # RADD-895: the row says where the bytes live — the "" sentinel that
        # meant "read the env at runtime" is gone (a migration backfilled it).
        if not fields.get("root_dir"):
            raise ConflictError(
                AttachmentEntity.HOST, reason="a filesystem host needs a root directory"
            )
    elif not fields.get("endpoint") or not fields.get("bucket"):
        raise ConflictError(
            AttachmentEntity.HOST, reason="an s3 host needs an endpoint and a bucket"
        )


#: Never in an event payload — a diff records that a credential CHANGED, no value.
SECRET_FIELDS: tuple[str, ...] = ("access_key", "secret_key")
_UNDIFFED: tuple[str, ...] = (*changes.DEFAULT_EXCLUDED_COLUMNS, "source")


async def _emit(
    session: AsyncSession,
    event_type: AttachmentEvent,
    host: StorageHost,
    actor_id: uuid.UUID | None,
    diff: list[dict] | None = None,
) -> None:
    await events.emit(
        session,
        event_type=event_type,
        entity_type=AttachmentEntity.HOST,
        entity_id=host.id,
        actor_id=actor_id,
        payload={"name": host.name, "host_type": host.host_type, "is_default": host.is_default},
        changes=diff,
    )


async def create_host(
    session: AsyncSession,
    data: StorageHostCreate,
    *,
    source: StorageHostSource = StorageHostSource.USER,
    actor_id: uuid.UUID | None = None,
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
        email_images_allowed=data.email_images_allowed,
        source=source.value,
    )
    session.add(host)
    await session.flush()
    # First host in is the default, so a single-host deploy is complete at once.
    if data.is_default or await _count(session) == 1:
        await make_default(session, host, emit_event=False)
    await _emit(session, AttachmentEvent.HOST_CREATED, host, actor_id)
    return host


async def update_host(
    session: AsyncSession,
    host_id: uuid.UUID,
    data: StorageHostUpdate,
    *,
    actor_id: uuid.UUID | None = None,
) -> StorageHost:
    host = await get_host(session, host_id)
    before = changes.snapshot(host, changes.column_fields(host, exclude=_UNDIFFED))
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
    if "email_images_allowed" in fields:
        host.email_images_allowed = bool(fields["email_images_allowed"])
    _validate(StorageHostType(host.host_type), _column_state(host))
    await session.flush()
    if fields.get("is_default"):
        await make_default(session, host, emit_event=False)  # folded into this diff
    await refresh_default_snapshot(session)
    await _emit(
        session,
        AttachmentEvent.HOST_UPDATED,
        host,
        actor_id,
        changes.diff_object(host, before, hidden=SECRET_FIELDS),
    )
    return host


def _column_state(host: StorageHost) -> dict:
    return {
        "endpoint": host.endpoint,
        "bucket": host.bucket,
        "root_dir": host.root_dir,
        "delivery_mode": host.delivery_mode,
    }


async def delete_host(
    session: AsyncSession, host_id: uuid.UUID, *, actor_id: uuid.UUID | None = None
) -> None:
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
    await _emit(session, AttachmentEvent.HOST_DELETED, host, actor_id)
    await session.delete(host)
    await session.flush()
    if was_default:  # promote another so a multi-host deploy keeps a default
        remaining = await list_hosts(session)
        if remaining:
            await make_default(session, remaining[0], actor_id=actor_id)
    await refresh_default_snapshot(session)


async def make_default(
    session: AsyncSession,
    host: StorageHost,
    *,
    actor_id: uuid.UUID | None = None,
    emit_event: bool = True,
) -> None:
    """Exactly one default, cleared in one statement (the connections idiom).
    Emits `storage_host.updated` (is_default false → true) unless the caller
    folds the flip into its own diff (`emit_event=False`)."""
    was_default = host.is_default
    await session.execute(
        update(StorageHost).where(StorageHost.id != host.id).values(is_default=False)
    )
    host.is_default = True
    await session.flush()
    await refresh_default_snapshot(session)
    if emit_event and not was_default:
        await _emit(
            session,
            AttachmentEvent.HOST_UPDATED,
            host,
            actor_id,
            [{"field": "is_default", "from": False, "to": True}],
        )


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
