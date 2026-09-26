"""Attachment flows (spec 102): buffered upload -> host selection -> per-host
client write -> row + event. Plus the BLOB API — the seam other modules
(jiraimport snapshots) store loose bytes through without creating attachment
rows or entering the routing chain (blobs pin the default host).
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from fastapi import Response, UploadFile
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import NotFoundError
from radd.modules.events import service as events

from . import hosts, thumbnails
from .clients import buffer_upload, client_for
from .models import Attachment, StorageHost
from .types import (
    AttachmentEntity,
    AttachmentEvent,
    AttachmentParentType,
    AttachmentState,
    AttachmentTooLarge,  # noqa: F401 — re-export: router/module wire the 413 handler
)

logger = logging.getLogger(__name__)

__all__ = [
    "AttachmentTooLarge",
    "save_upload",
    "get_attachment",
    "list_for_item",
    "repoint",
    "newest_per_parent",
    "delete_attachment",
    "purge",
    "remove_bytes",
    "download_response",
    "save_blob",
    "remove_blob",
    "read_blob",
    "BlobRef",
]


async def save_upload(
    session: AsyncSession,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    upload: UploadFile,
    actor_id: uuid.UUID,
    chosen_host_id: uuid.UUID | None = None,
    source_ip: str | None = None,
    host: StorageHost | None = None,
) -> Attachment:
    """Buffer (cap-enforced), route through the rule chain (unless the caller
    pinned a host), write, record, emit."""
    storage_name = uuid.uuid4().hex
    content_type = upload.content_type or "application/octet-stream"
    filename = upload.filename or "file"
    buffer, size = await buffer_upload(upload)
    try:
        if host is None:
            from . import parents, routing

            def _content() -> bytes:
                buffer.seek(0)
                data = buffer.read()
                buffer.seek(0)
                return data

            ctx = routing.RoutingContext(
                actor_id=actor_id,
                source_ip=source_ip,
                chosen_host_id=chosen_host_id,
                filename=filename,
                content_type=content_type,
                size_bytes=size,
                entity_type=entity_type,
                entity_id=entity_id,
                project_id=await parents.binding_for(entity_type).project_id_of(
                    session, entity_id
                ),
                content=_content,
            )
            host = await routing.decide(session, ctx)
        await client_for(host).save(storage_name, buffer, size=size, content_type=content_type)
    finally:
        buffer.close()

    attachment = Attachment(
        entity_type=entity_type,
        entity_id=entity_id,
        filename=filename,
        content_type=content_type,
        size_bytes=size,
        storage_name=storage_name,
        storage_host_id=host.id,
        state=AttachmentState.STORED.value,
        created_by=actor_id,
    )
    session.add(attachment)
    await session.flush()
    await events.emit(
        session,
        event_type=AttachmentEvent.CREATED,
        entity_type=AttachmentEntity.ATTACHMENT,
        entity_id=attachment.id,
        actor_id=actor_id,
        subjects={"item": attachment.item_id},  # None unless an item is the parent
        payload={
            "entity_type": attachment.entity_type,
            "entity_id": str(attachment.entity_id),
            "filename": attachment.filename,
            "size_bytes": size,
            "storage_host_id": str(host.id),
        },
    )
    return attachment


async def get_attachment(session: AsyncSession, attachment_id: uuid.UUID) -> Attachment:
    attachment = await session.get(Attachment, attachment_id)
    if attachment is None:
        raise NotFoundError(AttachmentEntity.ATTACHMENT, attachment_id)
    return attachment


async def list_for_entity(
    session: AsyncSession, entity_type: str, entity_id: uuid.UUID
) -> list[Attachment]:
    result = await session.execute(
        select(Attachment)
        .where(Attachment.entity_type == entity_type, Attachment.entity_id == entity_id)
        .order_by(Attachment.created_at)
    )
    return list(result.scalars())


async def list_for_item(session: AsyncSession, item_id: uuid.UUID) -> list[Attachment]:
    return await list_for_entity(session, AttachmentParentType.ITEM.value, item_id)


async def repoint(
    session: AsyncSession,
    attachment_ids: list[uuid.UUID],
    *,
    from_entity_type: str,
    from_entity_id: uuid.UUID,
    to_entity_type: str,
    to_entity_id: uuid.UUID,
) -> int:
    """Move the NAMED attachments between parents, touching only rows on the
    from-parent; returns how many moved. For `forms.staging.claim` (RADD-887) the
    from-filter IS the ownership check: a stolen id simply does not move."""
    if not attachment_ids:
        return 0
    owned = set(
        (
            await session.execute(
                select(Attachment.id).where(
                    Attachment.id.in_(attachment_ids),
                    Attachment.entity_type == from_entity_type,
                    Attachment.entity_id == from_entity_id,
                )
            )
        ).scalars()
    )
    if not owned:
        return 0
    await session.execute(
        update(Attachment)
        .where(Attachment.id.in_(owned))
        .values(entity_type=to_entity_type, entity_id=to_entity_id)
    )
    return len(owned)


async def newest_per_parent(
    session: AsyncSession, entity_type: str
) -> list[tuple[uuid.UUID, datetime]]:
    """(entity_id, newest created_at) per parent of this type, one grouped query
    (for `forms.staging.sweep_abandoned`, RADD-887)."""
    rows = await session.execute(
        select(Attachment.entity_id, func.max(Attachment.created_at))
        .where(Attachment.entity_type == entity_type)
        .group_by(Attachment.entity_id)
    )
    return [(entity_id, newest) for entity_id, newest in rows.all()]


async def download_response(
    session: AsyncSession, attachment: Attachment, *, width: int | None = None
):
    """Bytes (proxy hosts) or a 307 presigned redirect (presigned hosts).

    A honoured `width` (RADD-751's `?w=`) is always PROXIED: a presigned URL would
    hand back the original bytes and silently ignore the width.
    """
    host = await hosts.get_host(session, attachment.storage_host_id)
    client = client_for(host)
    if width and thumbnails.can_resize(attachment.content_type):
        data = await client.read(attachment.storage_name)
        smaller = await thumbnails.resized(data, attachment.content_type, width)
        if smaller is not None:
            body, content_type = smaller
            return Response(
                content=body,
                media_type=content_type,
                headers={
                    "X-Content-Type-Options": "nosniff",
                    "Content-Disposition": "inline",
                    # Immutable: a bucket's bytes for one attachment never change.
                    "Cache-Control": "private, max-age=31536000, immutable",
                },
            )
    return await client.response(attachment)


async def delete_attachment(
    session: AsyncSession,
    attachment: Attachment,
    *,
    actor_id: uuid.UUID,
) -> None:
    # Captured BEFORE the row goes: a consumer cannot look them up afterwards.
    item_id = attachment.item_id
    payload = {
        "entity_type": attachment.entity_type,
        "entity_id": str(attachment.entity_id),
        "filename": attachment.filename,
        "size_bytes": attachment.size_bytes,
    }
    entity_id = attachment.id
    refs = await purge(session, [attachment])
    await session.flush()
    await remove_bytes(session, refs)
    await events.emit(
        session,
        event_type=AttachmentEvent.DELETED,
        entity_type=AttachmentEntity.ATTACHMENT,
        entity_id=entity_id,
        actor_id=actor_id,
        subjects={"item": item_id},
        payload=payload,
    )


async def purge(session: AsyncSession, rows: list[Attachment]) -> list[tuple[uuid.UUID, str]]:
    """Delete these rows and their grants (no FK on the resource — the spec-92
    idiom); returns the `(host_id, storage_name)` refs whose bytes must go too."""
    from radd.modules.access import service as access_service

    from .acl import ATTACHMENT_RESOURCE

    refs = []
    for row in rows:
        refs.append((row.storage_host_id, row.storage_name))
        await access_service.clear_resource(session, ATTACHMENT_RESOURCE, str(row.id))
        await session.delete(row)
    return refs


async def remove_bytes(session: AsyncSession, refs: list[tuple[uuid.UUID, str]]) -> None:
    """Best-effort, after the rows are gone: an unreachable host leaves orphaned
    bytes, never a 500 or a stuck consumer."""
    for host_id, storage_name in refs:
        try:
            host = await hosts.get_host(session, host_id)
            await client_for(host).remove(storage_name)
        except Exception:  # noqa: BLE001
            logger.exception("attachments: removing %s from storage failed", storage_name)


# --- the blob API (other modules' loose bytes; no rows, no routing) -----------


@dataclass(frozen=True)
class BlobRef:
    storage_name: str
    host_id: uuid.UUID
    size_bytes: int


async def save_blob(
    session: AsyncSession, upload: UploadFile, *, content_type: str
) -> BlobRef:
    """Store loose bytes on the DEFAULT host under a fresh storage_name. The
    caller records the ref (jiraimport: jira_snapshot_blobs.storage_host_id)."""
    host = await hosts.require_default(session)
    storage_name = uuid.uuid4().hex
    buffer, size = await buffer_upload(upload)
    try:
        await client_for(host).save(storage_name, buffer, size=size, content_type=content_type)
    finally:
        buffer.close()
    return BlobRef(storage_name=storage_name, host_id=host.id, size_bytes=size)


async def _blob_host(session: AsyncSession, host_id: uuid.UUID | None) -> StorageHost:
    """A None host (pre-102 row) means the default host."""
    if host_id is not None:
        return await hosts.get_host(session, host_id)
    return await hosts.require_default(session)


async def remove_blob(
    session: AsyncSession, storage_name: str, *, host_id: uuid.UUID | None
) -> None:
    """Delete a blob; a failure is logged and re-raised."""
    try:
        host = await _blob_host(session, host_id)
        await client_for(host).remove(storage_name)
    except Exception:  # noqa: BLE001
        logger.warning("attachments: removing blob %s failed", storage_name, exc_info=True)
        raise


async def read_blob(
    session: AsyncSession, storage_name: str, *, host_id: uuid.UUID | None
) -> bytes:
    host = await _blob_host(session, host_id)
    return await client_for(host).read(storage_name)
