"""Attachment endpoints (spec 102). Permission checks delegate to the parent
binding (`parents.py`)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from radd.db import commit_before_streaming, get_session
from radd.modules.auth.deps import Actor, CurrentUser

from radd.exceptions import ForbiddenError

from . import acl, hosts, parents, service
from .models import Attachment
from .schemas import AttachmentRead, UploadContextRead, UploadOption
from .types import AttachmentParentType

router = APIRouter(tags=["attachments"])

Session = Annotated[AsyncSession, Depends(get_session)]


async def too_large_handler(request: Request, exc: service.AttachmentTooLarge) -> JSONResponse:
    return JSONResponse(status_code=413, content={"detail": str(exc)})


def _read(attachment: Attachment, names: dict[uuid.UUID, str], **update) -> AttachmentRead:
    return AttachmentRead.model_validate(attachment).model_copy(
        update={"storage_host_name": names.get(attachment.storage_host_id, ""), **update}
    )


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
    return _read(attachment, await hosts.name_map(session))


@router.get("/attachments", response_model=list[AttachmentRead])
async def list_attachments(
    entity_type: AttachmentParentType,
    entity_id: uuid.UUID,
    session: Session,
    user: Actor,
) -> list[AttachmentRead]:
    binding = parents.binding_for(entity_type.value)
    await binding.require_read(session, user, entity_id)
    attachments = await service.list_for_entity(session, entity_type.value, entity_id)
    verdicts = await acl.readable_map(session, user, attachments)
    names = await hosts.name_map(session)
    return [
        _read(attachment, names, restricted=verdicts[attachment.id][1])
        for attachment in attachments
        if verdicts[attachment.id][0]  # unreadable rows are filtered, not flagged
    ]


@router.get("/attachments/{attachment_id}")
async def download_attachment(
    attachment_id: uuid.UUID,
    session: Session,
    user: Actor,
    w: Annotated[int | None, Query(ge=1, le=4096, description="Display width in CSS pixels")] = None,
) -> Response:
    """Bytes for proxy-delivery hosts; a 307 to a short presigned URL otherwise.

    THE ACL chokepoint: both delivery modes mint here, so a deny means no bytes
    AND no presigned URL. `w` (RADD-751) is advisory: anything that cannot be
    resized serves the original.
    """
    attachment = await service.get_attachment(session, attachment_id)
    if not await acl.attachment_readable(session, user, attachment):
        raise ForbiddenError("you do not have access to this attachment")
    response = await service.download_response(session, attachment, width=w)
    # RADD-845: a large proxy-delivery stream must not idle the request tx
    # under it for the transfer's whole duration.
    await commit_before_streaming(session)
    return response


@router.delete("/attachments/{attachment_id}", status_code=204)
async def delete_attachment(
    attachment_id: uuid.UUID, session: Session, user: CurrentUser
) -> None:
    attachment = await service.get_attachment(session, attachment_id)
    await acl.require_deletable(session, user, attachment)  # the rule MCP shares (RADD-816)
    await service.delete_attachment(session, attachment, actor_id=user.id)


# --- the upload-choice context (spec 102 "always ask") -------------------------


@router.get("/storage/upload-context", response_model=UploadContextRead)
async def upload_context(
    request: Request,
    session: Session,
    user: CurrentUser,
    content_type: Annotated[list[str] | None, Query()] = None,
) -> UploadContextRead:
    """Whether to show the storage prompt before an upload, and its options. It
    shows only when the answer can MATTER: the chain is simulated for the
    gesture's content types, and a rule that would capture them first suppresses
    it (named in `preempted_by`). One selectable host = no prompt; the chain
    still arbitrates server-side either way."""
    from . import routing

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
