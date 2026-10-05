"""The attachment MCP tools: list, upload, download and delete the files on an issue or a
wiki page, through the parent bindings and service functions the REST routes use, so an
agent may do exactly what its principal may.

Bytes ride the JSON-RPC body as base64 — the server cannot see a path on the agent's
machine — under `settings.mcp_attachment_max_bytes` in both directions; the multipart
REST route is named for anything larger. A download answers with content blocks instead
of JSON: an IMAGE the agent can look at when the type serves inline, an embedded RESOURCE
blob otherwise. `permission` drives the catalog filter only (`kernel_enforced=False`): the
tools address an issue key or a page id, never a project, so the bindings enforce by row.
"""

import base64
import binascii
import io
import json
import mimetypes
import uuid
from collections.abc import Mapping
from typing import Any

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import Headers

from radd.config import settings
from radd.exceptions import ForbiddenError
from radd.kernel.mcptools import ToolContent, object_schema
from radd.kernel.specs import McpToolSpec
from radd.modules.auth.models import User
from radd.modules.auth.types import Permission
from radd.modules.items.service import get_item_by_key

from . import acl, clients, hosts, parents, service
from .models import Attachment
from .types import AttachmentParentType, serves_inline

#: The route the SPA embeds (`attachmentUrl` in web/src/lib/constants/api-paths.ts).
API_PATH = "/api/v1/attachments"
DEFAULT_CONTENT_TYPE = "application/octet-stream"


def _api_path(attachment_id: uuid.UUID) -> str:
    return f"{API_PATH}/{attachment_id}"


def _absolute(path: str) -> str:
    return f"{settings.app_base_url.rstrip('/')}{path}"


def markdown_for(attachment: Attachment) -> str:
    """What the editor writes for an uploaded file: an inline image embeds, anything else
    links. The path is relative, as the SPA's own uploads are, so a page body reads the
    same whichever client wrote it."""
    label = attachment.filename.replace("]", "\\]")
    path = _api_path(attachment.id)
    if serves_inline(attachment.content_type):
        return f"![{label}]({path})"
    return f"[{label}]({path})"


def _row(
    attachment: Attachment, names: Mapping[uuid.UUID, str], *, restricted: bool = False
) -> dict[str, Any]:
    return {
        "id": str(attachment.id),
        "entity_type": attachment.entity_type,
        "entity_id": str(attachment.entity_id),
        "filename": attachment.filename,
        "content_type": attachment.content_type,
        "size_bytes": attachment.size_bytes,
        "created_by": str(attachment.created_by) if attachment.created_by else None,
        "created_at": attachment.created_at.isoformat() if attachment.created_at else None,
        "restricted": restricted,
        "storage_host": names.get(attachment.storage_host_id, ""),
        "url": _absolute(_api_path(attachment.id)),
        "markdown": markdown_for(attachment),
    }


# --- addressing: an issue by key, a page by id — the way a person names them ---------

_PARENT_PROPERTIES: dict[str, Any] = {
    "key": {
        "type": "string",
        "description": "The issue's key, e.g. TD-42. Give this OR page_id.",
    },
    "page_id": {
        "type": "string",
        "description": "The wiki page's id (UUID), as get_page and search_pages list them. "
        "Give this OR key.",
    },
}

_ATTACHMENT_ID = {
    "type": "string",
    "description": "The attachment's id, as list_attachments or an upload receipt gives it.",
}


async def _parent(
    session: AsyncSession, actor: User, args: Mapping[str, Any]
) -> tuple[str, uuid.UUID, str]:
    """(entity_type, entity_id, label). An issue resolves THROUGH the actor's read, so a
    key the principal may not see answers not-found, never forbidden."""
    key, page_id = args.get("key"), args.get("page_id")
    if bool(key) == bool(page_id):
        raise ValueError("give exactly one of key (an issue) or page_id (a wiki page)")
    if key:
        item = await get_item_by_key(session, str(key), actor)
        return AttachmentParentType.ITEM.value, item.id, item.key
    try:
        resolved = uuid.UUID(str(page_id))
    except ValueError:
        raise ValueError("page_id must be a page's UUID") from None
    return AttachmentParentType.PAGE.value, resolved, str(resolved)


def _attachment_id(args: Mapping[str, Any]) -> uuid.UUID:
    try:
        return uuid.UUID(str(args["attachment_id"]))
    except ValueError:
        raise ValueError("attachment_id must be an attachment's UUID") from None


def _decode_payload(args: Mapping[str, Any]) -> bytes:
    try:
        data = base64.b64decode(str(args["content_base64"]), validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("content_base64 is not valid standard base64") from None
    if not data:
        raise ValueError("content_base64 decodes to nothing")
    limit = settings.mcp_attachment_max_bytes
    if len(data) > limit:
        raise ValueError(
            f"{len(data)} bytes is over the MCP inline limit of {limit} bytes; upload "
            f"larger files with a multipart POST to {_absolute(API_PATH)}"
        )
    return data


# --- the handlers ---------------------------------------------------------------------


async def _list_attachments(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    entity_type, entity_id, label = await _parent(session, actor, args)
    binding = parents.binding_for(entity_type)
    await binding.require_read(session, actor, entity_id)
    rows = await service.list_for_entity(session, entity_type, entity_id)
    verdicts = await acl.readable_map(session, actor, rows)
    names = await hosts.name_map(session)
    return {
        "parent": {"entity_type": entity_type, "entity_id": str(entity_id), "label": label},
        "attachments": [
            _row(row, names, restricted=verdicts[row.id][1])
            for row in rows
            if verdicts[row.id][0]  # unreadable rows are filtered, not flagged (as REST)
        ],
    }


async def _upload_attachment(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    entity_type, entity_id, _label = await _parent(session, actor, args)
    binding = parents.binding_for(entity_type)
    await binding.require_write(session, actor, entity_id)
    data = _decode_payload(args)
    filename = str(args["filename"]).strip() or "file"
    content_type = str(
        args.get("content_type") or mimetypes.guess_type(filename)[0] or DEFAULT_CONTENT_TYPE
    )
    upload = UploadFile(
        file=io.BytesIO(data),
        filename=filename,
        size=len(data),
        headers=Headers({"content-type": content_type}),
    )
    attachment = await service.save_upload(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
        upload=upload,
        actor_id=actor.id,
    )
    names = await hosts.name_map(session)
    return _row(attachment, names)


async def _download_attachment(
    session: AsyncSession, actor: User, args: Mapping[str, Any]
) -> Any:
    attachment = await service.get_attachment(session, _attachment_id(args))
    if not await acl.attachment_readable(session, actor, attachment):
        raise ForbiddenError("you do not have access to this attachment")
    limit = settings.mcp_attachment_max_bytes
    url = _absolute(_api_path(attachment.id))
    if attachment.size_bytes > limit:
        raise ValueError(
            f"{attachment.filename} is {attachment.size_bytes} bytes, over the MCP inline "
            f"limit of {limit} bytes; fetch it with GET {url}"
        )
    host = await hosts.get_host(session, attachment.storage_host_id)
    data = await clients.client_for(host).read(attachment.storage_name)
    names = await hosts.name_map(session)
    meta = _row(attachment, names)
    if serves_inline(attachment.content_type):
        payload = ToolContent.image_block(data, attachment.content_type)
    else:
        payload = ToolContent.resource_block(url, attachment.content_type, data)
    return ToolContent((ToolContent.text_block(json.dumps(meta, ensure_ascii=False)), payload))


async def _delete_attachment(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    attachment = await service.get_attachment(session, _attachment_id(args))
    await acl.require_deletable(session, actor, attachment)
    receipt = {"id": str(attachment.id), "filename": attachment.filename, "deleted": True}
    await service.delete_attachment(session, attachment, actor_id=actor.id)
    return receipt


# --- the specs --------------------------------------------------------------------------

LIST_ATTACHMENTS = McpToolSpec(
    name="list_attachments",
    description="The files attached to an issue (by key) or a wiki page (by id): id, name, "
    "type, size, who and when, the URL, and the Markdown that embeds it in a description "
    "or a page body.",
    input_schema=object_schema(dict(_PARENT_PROPERTIES)),
    handler=_list_attachments,
    kernel_enforced=False,
)

UPLOAD_ATTACHMENT = McpToolSpec(
    name="upload_attachment",
    description="Attach a file to an issue (by key) or a wiki page (by id). The bytes travel "
    "as base64 under the instance's inline limit; the receipt carries the URL and the "
    "Markdown to embed — a page attachment nothing references is invisible, so put that "
    "line in the body with update_page.",
    input_schema=object_schema(
        {
            **_PARENT_PROPERTIES,
            "filename": {"type": "string", "minLength": 1, "maxLength": 300},
            "content_base64": {
                "type": "string",
                "minLength": 1,
                "description": "The file's bytes, standard base64 (no data: prefix).",
            },
            "content_type": {
                "type": "string",
                "description": "MIME type; guessed from the filename when omitted.",
            },
        },
        ["filename", "content_base64"],
    ),
    handler=_upload_attachment,
    permission=Permission.ATTACHMENT_CREATE,
    project_scoped=True,
    kernel_enforced=False,
)

DOWNLOAD_ATTACHMENT = McpToolSpec(
    name="download_attachment",
    description="The bytes of one attachment: an image comes back as an image block you can "
    "look at, anything else as an embedded resource blob, with its metadata first. Over the "
    "inline limit the answer names the REST URL to fetch instead.",
    input_schema=object_schema({"attachment_id": _ATTACHMENT_ID}, ["attachment_id"]),
    handler=_download_attachment,
    kernel_enforced=False,
)

DELETE_ATTACHMENT = McpToolSpec(
    name="delete_attachment",
    description="Delete an attachment you uploaded (holders of attachment.delete, or a page "
    "space's admins, may delete anyone's). Bytes are immutable: to replace a file, delete it, "
    "upload the new one and re-embed its Markdown.",
    input_schema=object_schema({"attachment_id": _ATTACHMENT_ID}, ["attachment_id"]),
    handler=_delete_attachment,
    permission=Permission.ATTACHMENT_DELETE,
    project_scoped=True,
    kernel_enforced=False,
)

MCP_TOOLS: tuple[McpToolSpec, ...] = (
    LIST_ATTACHMENTS,
    UPLOAD_ATTACHMENT,
    DOWNLOAD_ATTACHMENT,
    DELETE_ATTACHMENT,
)
