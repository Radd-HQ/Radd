"""The comment MCP tools (RADD-1477): edit and delete a comment or a reply.

`comment_item` (items) writes; these change what was written. Each handler goes
through `service.update_comment` / `service.delete_comment`, so an agent may do
exactly what its principal may — the author, or a project manager — and a root
with replies is refused the same way REST refuses it. `permission` drives the
catalog filter only (`kernel_enforced=False`): the tools take a comment id and
name no project, so a kernel `require` could only ask for the atom GLOBALLY,
which would refuse the project-scoped keys the service admits by row.
"""

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from radd.kernel.mcptools import object_schema
from radd.kernel.specs import McpToolSpec
from radd.modules.auth.models import User
from radd.modules.auth.types import Permission

from . import service
from .schemas import CommentRead, CommentUpdate


def _comment_id_property() -> dict[str, Any]:
    return {
        "type": "string",
        "description": "The comment's id, as get_item lists them. A reply's id works the same way.",
    }


def update_comment_schema() -> dict[str, Any]:
    return object_schema(
        {
            "comment_id": _comment_id_property(),
            "body": {
                "type": "string",
                "minLength": 1,
                "description": "The new Markdown body. Omit to leave the text as it is.",
            },
            "visible_to_teams": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Team ids an INTERNAL comment is narrowed to (empty = every "
                "internal reader). A reply's teams may only narrow its thread's.",
            },
        },
        ["comment_id"],
    )


def delete_comment_schema() -> dict[str, Any]:
    return object_schema({"comment_id": _comment_id_property()}, ["comment_id"])


def receipt(read: CommentRead) -> dict[str, Any]:
    """RADD-861: a write answers with a receipt, not the body the agent just wrote."""
    return {
        "id": str(read.id),
        "parent_comment_id": str(read.parent_comment_id) if read.parent_comment_id else None,
        "is_thread": read.is_thread,
        "resolved": read.resolved_at is not None,
        "visibility": read.visibility.value,
        "updated_at": read.updated_at.isoformat(),
    }


def update_from_args(args: Mapping[str, Any]) -> CommentUpdate:
    """The PATCH body an agent's arguments describe; an absent key changes nothing."""
    teams = args.get("visible_to_teams")
    return CommentUpdate(
        body=str(args["body"]) if args.get("body") is not None else None,
        visible_to_teams=[uuid.UUID(str(team)) for team in teams] if teams is not None else None,
    )


async def _update_comment(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    read = await service.update_comment(
        session, uuid.UUID(str(args["comment_id"])), update_from_args(args), actor
    )
    return receipt(read)


async def _delete_comment(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    comment_id = uuid.UUID(str(args["comment_id"]))
    await service.delete_comment(session, comment_id, actor)
    return {"id": str(comment_id), "deleted": True}


UPDATE_COMMENT = McpToolSpec(
    name="update_comment",
    description="Edit a comment or a reply you wrote (a project manager may edit anyone's): "
    "its body, or the teams an internal one is narrowed to.",
    input_schema=update_comment_schema(),
    handler=_update_comment,
    permission=Permission.COMMENT_WRITE,
    project_scoped=True,
    kernel_enforced=False,
)

DELETE_COMMENT = McpToolSpec(
    name="delete_comment",
    description="Delete a comment or a reply you wrote (a project manager may delete anyone's). "
    "A comment that still has replies is refused: delete the replies first.",
    input_schema=delete_comment_schema(),
    handler=_delete_comment,
    permission=Permission.COMMENT_DELETE,
    project_scoped=True,
    kernel_enforced=False,
)

MCP_TOOLS: tuple[McpToolSpec, ...] = (UPDATE_COMMENT, DELETE_COMMENT)
