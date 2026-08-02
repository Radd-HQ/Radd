"""Attachment endpoints (spec 102): polymorphic canonical routes + the legacy
item aliases every pre-102 consumer (SDK/MCP/importer) still calls.

Permission checks delegate to the parent binding (parents.py): item parents ->
project-scoped item perms; doc_page parents -> the global doc atoms. Delete
keeps the comments mirror: uploaders remove their own, admins remove anyone's.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import get_session
from radd.modules.auth.deps import CurrentUser

from radd.exceptions import ForbiddenError

from . import acl, parents, service
from .schemas import AttachmentRead, UploadContextRead, UploadOption
from .types import AttachmentParentType

router = APIRouter(tags=["attachments"])

Session = Annotated[AsyncSession, Depends(get_session)]


async def too_large_handler(request: Request, exc: service.AttachmentTooLarge) -> JSONResponse:
    return JSONResponse(status_code=413, content={"detail": str(exc)})


# --- canonical polymorphic routes ---------------------------------------------


@router.post("/attachments", response_model=AttachmentRead, status_code=201)
async def upload_attachment(
    request: Request,
    file: UploadFile,
    entity_type: Annotated[AttachmentParentType, Form()],
    entity_id: Annotated[uuid.UUID, Form()],
    session: Session,
    user: CurrentUser,
    chosen_host_id: Annotated[uuid.UUID | None, Form()] = None,
) -> AttachmentRead:
    binding = parents.binding_for(entity_type.value)
    await binding.require_write(session, user, entity_id)
    attachment = await service.save_upload(
        session,
        entity_type=entity_type.value,
        entity_id=entity_id,
        upload=file,
        actor_id=user.id,
        chosen_host_id=chosen_host_id,
        source_ip=getattr(request.state, "client_ip", None),
    )
    from . import hosts

    names = await hosts.name_map(session)
    return AttachmentRead.model_validate(attachment).model_copy(
        update={"storage_host_name": names.get(attachment.storage_host_id, "")}
    )


@router.get("/attachments", response_model=list[AttachmentRead])
async def list_attachments(
    entity_type: AttachmentParentType,
    entity_id: uuid.UUID,
    session: Session,
    user: CurrentUser,
) -> list[AttachmentRead]:
    binding = parents.binding_for(entity_type.value)
    await binding.require_read(session, user, entity_id)
    attachments = await service.list_for_entity(session, entity_type.value, entity_id)
    verdicts = await acl.readable_map(session, user, attachments)
    from . import hosts

    names = await hosts.name_map(session)
    return [
        AttachmentRead.model_validate(attachment).model_copy(
            update={
                "restricted": verdicts[attachment.id][1],
                "storage_host_name": names.get(attachment.storage_host_id, ""),
            }
        )
        for attachment in attachments
        if verdicts[attachment.id][0]  # unreadable rows are filtered, not flagged
    ]


@router.get("/attachments/{attachment_id}")
async def download_attachment(
    attachment_id: uuid.UUID, session: Session, user: CurrentUser
) -> Response:
    """Bytes for proxy-delivery hosts; a 307 to a short presigned URL otherwise.

    THE ACL chokepoint (spec 102): both delivery modes mint here, so a deny
    means no bytes AND no presigned URL ever exist for this caller.
    """
    attachment = await service.get_attachment(session, attachment_id)
    if not await acl.attachment_readable(session, user, attachment):
        raise ForbiddenError("you do not have access to this attachment")
    return await service.download_response(session, attachment)


@router.delete("/attachments/{attachment_id}", status_code=204)
async def delete_attachment(
    attachment_id: uuid.UUID, session: Session, user: CurrentUser
) -> None:
    attachment = await service.get_attachment(session, attachment_id)
    binding = parents.binding_for(attachment.entity_type)
    # Uploader may remove their own; otherwise the parent's admin (mirrors comments).
    if attachment.created_by == user.id:
        await binding.require_write(session, user, attachment.entity_id)
    else:
        await binding.require_admin(session, user, attachment.entity_id)
    await service.delete_attachment(session, attachment, actor_id=user.id)


# --- legacy item aliases (pre-102 API surface, kept working) -------------------


@router.post("/items/{item_id}/attachments", response_model=AttachmentRead, status_code=201)
async def upload_item_attachment(
    request: Request, item_id: uuid.UUID, file: UploadFile, session: Session, user: CurrentUser
) -> AttachmentRead:
    return await upload_attachment(
        request, file, AttachmentParentType.ITEM, item_id, session, user
    )


@router.get("/items/{item_id}/attachments", response_model=list[AttachmentRead])
async def list_item_attachments(
    item_id: uuid.UUID, session: Session, user: CurrentUser
) -> list[AttachmentRead]:
    return await list_attachments(AttachmentParentType.ITEM, item_id, session, user)


# --- the upload-choice context (spec 102 "always ask") -------------------------


@router.get("/storage/upload-context", response_model=UploadContextRead)
async def upload_context(
    request: Request,
    session: Session,
    user: CurrentUser,
    content_type: Annotated[list[str] | None, Query()] = None,
) -> UploadContextRead:
    """What the SPA's upload seam needs to know BEFORE any upload: whether to
    pop the storage prompt, and the options to offer. The prompt only shows
    when the answer can MATTER (spec 102): callers pass the gesture's content
    types, and the chain is simulated — an earlier rule that would capture
    these files (an LLM rule covering image/*, a CIDR rule matching this IP)
    suppresses the ask and is named in `preempted_by`. Exactly one selectable
    host -> no prompt, the SPA auto-sends it; the chain still arbitrates
    server-side either way."""
    from . import hosts, routing

    reachable, preempted_by = await routing.engine.choice_reachable(
        session,
        source_ip=getattr(request.state, "client_ip", None),
        content_types=[ct for ct in (content_type or []) if ct],
    )
    if not reachable:
        return UploadContextRead(ask_user=False, options=[], preempted_by=preempted_by)
    selectable = await hosts.selectable_hosts(session)
    options = [UploadOption(id=host.id, name=host.name) for host in selectable]
    return UploadContextRead(ask_user=len(options) >= 2, options=options)
