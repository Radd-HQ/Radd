"""Attachment flows (spec 102): buffered upload -> host selection -> per-host
client write -> row + event. Plus the BLOB API — the seam other modules
(jiraimport snapshots) store loose bytes through without creating attachment
rows or entering the routing chain (blobs pin the default host).
"""

import logging
import uuid
from dataclasses import dataclass

from fastapi import Response, UploadFile
from sqlalchemy import select
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
    "delete_attachment",
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
        filename=upload.filename or "file",
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
        payload={
            # item_id stays for item parents so notify/automation item-scoping
            # keeps working; a doc-parented event simply has no item.
            "item_id": str(attachment.item_id) if attachment.item_id else None,
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


async def download_response(
    session: AsyncSession, attachment: Attachment, *, width: int | None = None
):
    """Bytes (proxy hosts) or a 307 presigned redirect (presigned hosts).

    `width` is the `?w=` convention of RADD-751. When it is honoured the response
    is always PROXIED, whatever the host's delivery mode: a presigned URL points
    the browser straight at the object store, which will hand back the original
    bytes — so redirecting would silently ignore the width the document asked
    for. Serving fewer bytes is the point, and it is worth the proxy hop.
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
    storage_name = attachment.storage_name
    host_id = attachment.storage_host_id
    payload = {
        "item_id": str(attachment.item_id) if attachment.item_id else None,
        "entity_type": attachment.entity_type,
        "entity_id": str(attachment.entity_id),
        "filename": attachment.filename,
        "size_bytes": attachment.size_bytes,
    }
    entity_id = attachment.id
    await session.delete(attachment)
    await session.flush()
    # Grants have no FK on the resource — clear them with the row (spec 92 idiom).
    from radd.modules.access import service as access_service

    from .acl import ATTACHMENT_RESOURCE

    await access_service.clear_resource(session, ATTACHMENT_RESOURCE, str(entity_id))
    await _remove_bytes(session, host_id, storage_name)
    await events.emit(
        session,
        event_type=AttachmentEvent.DELETED,
        entity_type=AttachmentEntity.ATTACHMENT,
        entity_id=entity_id,
        actor_id=actor_id,
        payload=payload,
    )


async def _remove_bytes(session: AsyncSession, host_id: uuid.UUID, storage_name: str) -> None:
    try:
        host = await hosts.get_host(session, host_id)
        await client_for(host).remove(storage_name)
    except Exception:  # noqa: BLE001
        # Best-effort: the DB row is already gone; orphaned bytes beat a 500.
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


async def remove_blob(
    session: AsyncSession, storage_name: str, *, host_id: uuid.UUID | None
) -> None:
    """Best-effort blob delete; a None host (pre-102 row) means the default host."""
    try:
        host = (
            await hosts.get_host(session, host_id)
            if host_id is not None
            else await hosts.require_default(session)
        )
        await client_for(host).remove(storage_name)
    except Exception:  # noqa: BLE001
        logger.warning("attachments: removing blob %s failed", storage_name, exc_info=True)
        raise


async def read_blob(
    session: AsyncSession, storage_name: str, *, host_id: uuid.UUID | None
) -> bytes:
    host = (
        await hosts.get_host(session, host_id)
        if host_id is not None
        else await hosts.require_default(session)
    )
    return await client_for(host).read(storage_name)
