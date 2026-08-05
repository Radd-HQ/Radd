"""The item MCP tools (specs 45/114), declared by their owner (RADD-889).

Handlers moved verbatim from mcp/tools.py: every one resolves the PAT-authed
actor's request through the ordinary service/authz seams — an agent can do
exactly what its principal may do, nothing more. The specs below ARE the
spec-114 annotations (`permission` drives the caller filter), while enforcement
stays exactly where it was — inside the handlers' service seams — so
`kernel_enforced=False`: a blanket dispatcher `require` would re-refuse the
scoped keys RADD-672 admitted.

comments is a weak dependency (it loads after items), so its imports stay
inside the handlers, as do the itemtypes/cycles resolvers' (matching the
pre-move code).
"""

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import NotFoundError
from radd.kernel.mcptools import limit_arg
from radd.kernel.specs import McpToolSpec
from radd.modules.auth import service as auth_service
from radd.modules.auth.models import User
from radd.modules.auth.types import AuthEntity, Permission
from radd.modules.projects import service as projects_service
from radd.modules.workflow import service as workflow_service
from radd.modules.workflow import transitions as workflow_transitions
from radd.modules.workflow.types import StateEntity

from . import service as items_service
from .enums import ItemEntity, ItemKind, Priority
from .filters import ItemListFilters
from .mcpschemas import (
    GET_ITEM_COMMENTS_TAIL,
    comment_item_schema,
    create_item_schema,
    get_allowed_transitions_schema,
    get_item_schema,
    link_items_schema,
    search_items_schema,
    transition_item_schema,
    unlink_items_schema,
    update_item_schema,
)
from .schemas import ItemCreate, ItemLinkCreate, ItemRead, ItemUpdate

# --- shared resolvers (name -> id, RADD-673: names in, ids resolved server-side) ---


async def _state_id(session: AsyncSession, project_id: uuid.UUID, name: str) -> uuid.UUID:
    for state in await workflow_service.list_states(session, project_id):
        if state.name.lower() == name.lower():
            return state.id
    raise NotFoundError(StateEntity.STATE, name)


async def _user_id_by_email(session: AsyncSession, email: str) -> uuid.UUID:
    user = await auth_service.get_user_by_email(session, email)
    if user is None:
        raise NotFoundError(AuthEntity.USER, email)
    return user.id


async def _type_id(session: AsyncSession, project_id: uuid.UUID, name: str) -> uuid.UUID:
    from radd.modules.itemtypes import service as itemtypes_service

    for issue_type in await itemtypes_service.list_types(session, project_id):
        if issue_type.name.lower() == name.lower():
            return issue_type.id
    raise NotFoundError("issue type", name)


async def _cycle_id(session: AsyncSession, name: str) -> uuid.UUID:
    from radd.modules.cycles import service as cycles_service

    for cycle in await cycles_service.list_cycles(session):
        if cycle.name.lower() == name.lower():
            return cycle.id
    raise NotFoundError("cycle", name)


def _item_summary(read: ItemRead) -> dict[str, Any]:
    return {
        "key": read.key,
        "kind": read.kind.value,
        "title": read.title,
        "state": read.state.name,
        "priority": read.priority.value,
        "assignee": read.assignee.name if read.assignee else None,
        "labels": read.labels,
        "updated_at": read.updated_at.isoformat(),
    }


def _item_write_fields(args: Mapping[str, Any]) -> dict[str, Any]:
    """Write values shared by create/update that need no DB resolution."""
    values: dict[str, Any] = {}
    if args.get("title") is not None:
        values["title"] = str(args["title"])
    if args.get("description") is not None:
        values["description"] = str(args["description"])
    if args.get("priority") is not None:
        values["priority"] = Priority(args["priority"])
    if args.get("labels") is not None:
        values["labels"] = [str(label) for label in args["labels"]]
    if args.get("custom_fields") is not None:
        values["custom_fields"] = dict(args["custom_fields"])
    return values


def receipt(read: Any) -> dict:
    """RADD-861: WRITE tools answer with a receipt, not the hydrated item.

    The agent just AUTHORED what a full echo would repeat — the multi-KB
    description, the comment body — and every echoed byte sits in its context
    for the session's remainder, re-read on every later call. Reads stay full
    (that is their job); errors stay verbose (the reason text is the value).
    """
    return {
        "key": read.key,
        "id": str(read.id),
        "state": getattr(getattr(read, "state", None), "name", None),
        "updated_at": read.updated_at.isoformat() if getattr(read, "updated_at", None) else None,
    }


# --- tool handlers ---


async def _search_items(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    slq = str(args["slq"]).strip()
    reads = await items_service.list_items(
        session, actor=actor, filters=ItemListFilters(), q=slq or None,
        limit=limit_arg(args), offset=0,
    )
    return {"items": [_item_summary(read) for read in reads], "count": len(reads)}


async def _link_items(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    """Link two items by KEY (RADD-739).

    Keys, not ids or per-project numbers: every other tool in the catalog
    addresses items by key, and an agent that just created two items holds their
    keys and nothing else. Enforcement is `items_service.add_item_link`'s own —
    it requires `item.update` on the SOURCE item's project and validates the type
    against the spec-91 catalog, so nothing is re-derived here.
    """
    source = await items_service.get_item_by_key(session, str(args["from_key"]), actor=actor)
    target = await items_service.get_item_by_key(session, str(args["to_key"]), actor=actor)
    read = await items_service.add_item_link(
        session,
        source.id,
        ItemLinkCreate(target_id=target.id, link_type=str(args["type"])),
        actor=actor,
    )
    return {
        "key": read.key,
        "links": {
            "outgoing": [
                {"type": link.link_type, "key": link.item.key, "title": link.item.title}
                for link in read.links.outgoing
            ],
            "incoming": [
                {"type": link.link_type, "key": link.item.key, "title": link.item.title}
                for link in read.links.incoming
            ],
        },
    }


async def _unlink_items(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    """Remove a link, addressed the way it was created rather than by link id —
    an agent that made a link does not keep its uuid, and asking it to list the
    item first to find one would make removal a two-call dance."""
    source = await items_service.get_item_by_key(session, str(args["from_key"]), actor=actor)
    target = await items_service.get_item_by_key(session, str(args["to_key"]), actor=actor)
    link_type = str(args["type"])
    match = next(
        (
            link
            for link in source.links.outgoing
            if link.item.key == target.key and link.link_type == link_type
        ),
        None,
    )
    if match is None:
        raise NotFoundError(
            ItemEntity.LINK, f"{source.key} -{link_type}-> {target.key}"
        )
    await items_service.remove_item_link(session, source.id, match.id, actor=actor)
    return {"removed": {"from": source.key, "to": target.key, "type": link_type}}


async def _get_item(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    from radd.modules.comments import service as comments_service

    read = await items_service.get_item_by_key(session, str(args["key"]), actor=actor)
    comments = await comments_service.list_comments(session, read.id, actor=actor)
    tail = comments[-GET_ITEM_COMMENTS_TAIL:]
    return {
        "item": read.model_dump(mode="json"),
        "comments": [comment.model_dump(mode="json") for comment in tail],
        "comment_total": len(comments),
    }


async def _resolve_relational_writes(
    session: AsyncSession,
    actor: User,
    project_id: uuid.UUID,
    args: Mapping[str, Any],
    values: dict[str, Any],
) -> None:
    """type/parent/cycle/estimate shared by create+update (RADD-673). Present-and-
    null clears, like assignee_email — pydantic's model_fields_set carries the
    distinction through to the service."""
    if args.get("type") is not None:
        values["type_id"] = await _type_id(session, project_id, str(args["type"]))
    if "parent" in args:
        parent_key = args["parent"]
        values["parent_id"] = (
            (await items_service.get_item_by_key(session, str(parent_key), actor=actor)).id
            if parent_key
            else None
        )
    if "cycle" in args:
        cycle_name = args["cycle"]
        values["cycle_id"] = await _cycle_id(session, str(cycle_name)) if cycle_name else None
    if "estimate_points" in args:
        raw_points = args["estimate_points"]
        values["estimate_points"] = float(raw_points) if raw_points is not None else None


async def _create_item(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    project = await projects_service.get_by_key(session, str(args["project_key"]))
    values = _item_write_fields(args)
    values["project_id"] = project.id
    values["title"] = str(args["title"])
    if args.get("kind") is not None:
        values["kind"] = ItemKind(args["kind"])
    if args.get("state") is not None:
        values["state_id"] = await _state_id(session, project.id, str(args["state"]))
    if args.get("assignee_email"):
        values["assignee_id"] = await _user_id_by_email(session, str(args["assignee_email"]))
    await _resolve_relational_writes(session, actor, project.id, args, values)
    read = await items_service.create_item(session, ItemCreate(**values), actor=actor)
    return receipt(read)


async def _update_item(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    current = await items_service.get_item_by_key(session, str(args["key"]), actor=actor)
    values = _item_write_fields(args)
    if args.get("state") is not None:
        values["state_id"] = await _state_id(session, current.project_id, str(args["state"]))
    if "assignee_email" in args:  # present-and-null clears the assignee
        email = args["assignee_email"]
        values["assignee_id"] = await _user_id_by_email(session, str(email)) if email else None
    await _resolve_relational_writes(session, actor, current.project_id, args, values)
    read = await items_service.update_item(session, current.id, ItemUpdate(**values), actor=actor)
    return receipt(read)


async def _comment_item(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    from radd.modules.comments import service as comments_service
    from radd.modules.comments.schemas import CommentCreate
    from radd.modules.comments.types import CommentVisibility

    current = await items_service.get_item_by_key(session, str(args["key"]), actor=actor)
    visibility = CommentVisibility.INTERNAL if args.get("internal") else CommentVisibility.PUBLIC
    comment = await comments_service.create_comment(
        session,
        current.id,
        CommentCreate(body=str(args["body"]), visibility=visibility),
        actor=actor,
    )
    # RADD-861: the body just came FROM the agent — never echo it back.
    return {"id": str(comment.id), "created_at": comment.created_at.isoformat()}


async def _get_allowed_transitions(
    session: AsyncSession, actor: User, args: Mapping[str, Any]
) -> Any:
    read = await items_service.get_item_by_key(session, str(args["key"]), actor=actor)
    item = await items_service.require_item(session, read.id)
    project = await projects_service.get_project(session, read.project_id)
    allowed = await workflow_transitions.allowed_transitions(session, project, item)
    return allowed.model_dump(mode="json") if hasattr(allowed, "model_dump") else allowed


async def _transition_item(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    """A guard refusal is a DOMAIN error carrying the reason, which the router
    turns into an isError result with that text — the agent learns why."""
    current = await items_service.get_item_by_key(session, str(args["key"]), actor=actor)
    state_id = await _state_id(session, current.project_id, str(args["state"]))
    read = await items_service.update_item(
        session, current.id, ItemUpdate(state_id=state_id), actor=actor
    )
    return receipt(read)


# --- the specs (the spec IS the spec-114 annotation) ---

SEARCH_ITEMS = McpToolSpec(
    name="search_items",
    description="Search work items with an SLQ query (results are RBAC-scoped "
    "to projects the authenticated principal may read).",
    input_schema=search_items_schema(),
    handler=_search_items,
    permission=Permission.ITEM_READ,
    project_scoped=True,
    kernel_enforced=False,
)

LINK_ITEMS = McpToolSpec(
    name="link_items",
    description="Link two work items — e.g. one blocks another. Dependency "
    "links are how a plan records what has to happen before what; without "
    "them the ordering survives only as prose in a description.",
    input_schema=link_items_schema(),
    input_schema_builder=link_items_schema,
    handler=_link_items,
    # RADD-739: the same atom `items/service/links.py` already requires on the
    # SOURCE item's project, so enforcement is inherited rather than re-derived.
    permission=Permission.ITEM_UPDATE,
    project_scoped=True,
    kernel_enforced=False,
)

UNLINK_ITEMS = McpToolSpec(
    name="unlink_items",
    description="Remove a link between two work items.",
    input_schema=unlink_items_schema(),
    input_schema_builder=unlink_items_schema,
    handler=_unlink_items,
    permission=Permission.ITEM_UPDATE,
    project_scoped=True,
    kernel_enforced=False,
)

GET_ITEM = McpToolSpec(
    name="get_item",
    description="Fetch one work item by key: full detail including custom "
    f"fields inline, plus the {GET_ITEM_COMMENTS_TAIL} most recent comments.",
    input_schema=get_item_schema(),
    handler=_get_item,
    permission=Permission.ITEM_READ,
    project_scoped=True,
    kernel_enforced=False,
)

CREATE_ITEM = McpToolSpec(
    name="create_item",
    description="Create a work item in a project (addressed by project key).",
    input_schema=create_item_schema(),
    input_schema_builder=create_item_schema,
    handler=_create_item,
    permission=Permission.ITEM_CREATE,
    project_scoped=True,
    project_param="project_key",
    kernel_enforced=False,
)

UPDATE_ITEM = McpToolSpec(
    name="update_item",
    description="Update fields of an existing work item (omitted fields are "
    "unchanged; custom_fields merge into existing values).",
    input_schema=update_item_schema(),
    input_schema_builder=update_item_schema,
    handler=_update_item,
    permission=Permission.ITEM_UPDATE,
    project_scoped=True,
    kernel_enforced=False,
)

COMMENT_ITEM = McpToolSpec(
    name="comment_item",
    description="Add a comment to a work item.",
    input_schema=comment_item_schema(),
    handler=_comment_item,
    permission=Permission.COMMENT_WRITE,
    project_scoped=True,
    kernel_enforced=False,
)

GET_ALLOWED_TRANSITIONS = McpToolSpec(
    name="get_allowed_transitions",
    description="Which workflow states this item may move to right now, and for "
    "the ones it may not, WHY (spec-107 transition guards).",
    input_schema=get_allowed_transitions_schema(),
    handler=_get_allowed_transitions,
    permission=Permission.ITEM_READ,
    project_scoped=True,
    kernel_enforced=False,
)

TRANSITION_ITEM = McpToolSpec(
    name="transition_item",
    description="Move an item to a workflow state by NAME. A guard refusal comes "
    "back as the reason text, not a bare error.",
    input_schema=transition_item_schema(),
    handler=_transition_item,
    permission=Permission.ITEM_UPDATE,
    project_scoped=True,
    kernel_enforced=False,
)

MCP_TOOLS = (
    SEARCH_ITEMS,
    LINK_ITEMS,
    UNLINK_ITEMS,
    GET_ITEM,
    CREATE_ITEM,
    UPDATE_ITEM,
    COMMENT_ITEM,
    GET_ALLOWED_TRANSITIONS,
    TRANSITION_ITEM,
)
