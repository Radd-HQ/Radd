"""MCP tool dispatch (spec 45): one handler per catalog tool.

Every handler resolves the PAT-authed actor's request through the ordinary
service/authz seams — an agent can do exactly what its principal may do,
nothing more. Domain failures (RaddError subclasses) bubble up for the router
to shape into `isError: true` results; the catalog itself lives in catalog.py,
docs-module feature detection in docs_bridge.py.
"""

import uuid
from collections.abc import Callable, Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import NotFoundError
from radd.modules.auth import authz, service as auth_service
from radd.modules.auth.authz import Permission
from radd.modules.auth.models import User
from radd.modules.auth.types import AuthEntity
from radd.modules.comments import service as comments_service
from radd.modules.comments.schemas import CommentCreate
from radd.modules.comments.types import CommentVisibility
from radd.modules.items import service as items_service
from radd.modules.items.enums import ItemKind, Priority
from radd.modules.items.filters import ItemListFilters
from radd.modules.items.schemas import ItemCreate, ItemRead, ItemUpdate
from radd.modules.workflow import service as workflow_service
from radd.modules.workflow.types import StateEntity
from radd.modules.projects import service as projects_service
from radd.modules.projects.types import ProjectEntity

from . import docs_bridge
from .catalog import build_catalog, live_catalog  # re-export: the module's tool surface
from .types import (
    DOC_TOOLS,
    GET_ITEM_COMMENTS_TAIL,
    SEARCH_LIMIT_DEFAULT,
    SEARCH_LIMIT_MAX,
    McpTool,
)

__all__ = ["UnknownToolError", "build_catalog", "call_tool", "docs_available", "live_catalog"]

docs_available = docs_bridge.docs_available


class UnknownToolError(Exception):
    """tools/call named a tool outside the catalog -> JSON-RPC INVALID_PARAMS
    (deliberately NOT a RaddError: it must not become an isError tool result)."""

    def __init__(self, name: str):
        super().__init__(f"unknown tool '{name}'")


# --- shared resolvers ---


def _limit(args: Mapping[str, Any]) -> int:
    raw = args.get("limit", SEARCH_LIMIT_DEFAULT)
    return max(1, min(int(raw), SEARCH_LIMIT_MAX))


async def _project_by_key(session: AsyncSession, key: str):
    for project in await projects_service.list_projects(session):
        if project.key == key.upper():
            return project
    raise NotFoundError(ProjectEntity.PROJECT, key)


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


# --- tracker tool handlers ---


async def _search_items(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    slq = str(args["slq"]).strip()
    reads = await items_service.list_items(
        session, actor=actor, filters=ItemListFilters(), q=slq or None, limit=_limit(args), offset=0
    )
    return {"items": [_item_summary(read) for read in reads], "count": len(reads)}


async def _find_items(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    """Hybrid text search (spec 103): routes through search.service.search, so
    every MCP client inherits FTS+vector fusion — and any future ranking
    upgrade — with no client-side change."""
    from radd.modules.search import service as search_service

    hits = await search_service.search(
        session, actor, str(args["query"]), limit=_limit(args)
    )
    return {
        "items": [
            {
                "key": hit.key,
                "title": hit.title,
                "snippet": hit.snippet,
            }
            for hit in hits
        ],
        "count": len(hits),
    }


async def _get_item(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    read = await items_service.get_item_by_key(session, str(args["key"]), actor=actor)
    comments = await comments_service.list_comments(session, read.id, actor=actor)
    tail = comments[-GET_ITEM_COMMENTS_TAIL:]
    return {
        "item": read.model_dump(mode="json"),
        "comments": [comment.model_dump(mode="json") for comment in tail],
        "comment_total": len(comments),
    }


async def _create_item(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    project = await _project_by_key(session, str(args["project_key"]))
    values = _item_write_fields(args)
    values["project_id"] = project.id
    values["title"] = str(args["title"])
    if args.get("kind") is not None:
        values["kind"] = ItemKind(args["kind"])
    if args.get("state") is not None:
        values["state_id"] = await _state_id(session, project.id, str(args["state"]))
    if args.get("assignee_email"):
        values["assignee_id"] = await _user_id_by_email(session, str(args["assignee_email"]))
    read = await items_service.create_item(session, ItemCreate(**values), actor=actor)
    return read.model_dump(mode="json")


async def _update_item(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    current = await items_service.get_item_by_key(session, str(args["key"]), actor=actor)
    values = _item_write_fields(args)
    if args.get("state") is not None:
        values["state_id"] = await _state_id(session, current.project_id, str(args["state"]))
    if "assignee_email" in args:  # present-and-null clears the assignee
        email = args["assignee_email"]
        values["assignee_id"] = await _user_id_by_email(session, str(email)) if email else None
    read = await items_service.update_item(session, current.id, ItemUpdate(**values), actor=actor)
    return read.model_dump(mode="json")


async def _comment_item(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    current = await items_service.get_item_by_key(session, str(args["key"]), actor=actor)
    visibility = CommentVisibility.INTERNAL if args.get("internal") else CommentVisibility.PUBLIC
    comment = await comments_service.create_comment(
        session,
        current.id,
        CommentCreate(body=str(args["body"]), visibility=visibility),
        actor=actor,
    )
    return comment.model_dump(mode="json")


async def _list_projects(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    # Same gate as GET /projects: any active user with item.read (spec 86).
    await authz.require(session, actor, Permission.ITEM_READ)
    projects = await projects_service.list_projects(session)
    return {
        "projects": [
            {"key": project.key, "name": project.name, "id": str(project.id)}
            for project in projects
        ]
    }


# --- doc tool handlers (feature-detected, see docs_bridge) ---


async def _get_doc_page(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    functions = docs_bridge.docs_functions()
    if functions is None:
        raise UnknownToolError(McpTool.GET_DOC_PAGE)
    page_id = uuid.UUID(str(args["id"]))
    result = await docs_bridge.call_docs(functions[0], session, actor, page_id=page_id, id=page_id)
    return docs_bridge.jsonable(result)


async def _search_docs(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    functions = docs_bridge.docs_functions()
    if functions is None:
        raise UnknownToolError(McpTool.SEARCH_DOCS)
    query = str(args["query"])
    limit = _limit(args)
    # Spec 86: docs are global — a single search over every space.
    result = await docs_bridge.call_docs(
        functions[1],
        session,
        actor,
        q=query,
        query=query,
        text=query,
        limit=limit,
    )
    jsonable = docs_bridge.jsonable(result)
    results = jsonable if isinstance(jsonable, list) else [jsonable]
    return results[:limit]


# --- dispatch ---

_HANDLERS: dict[McpTool, Callable[..., Any]] = {
    McpTool.SEARCH_ITEMS: _search_items,
    McpTool.FIND_ITEMS: _find_items,
    McpTool.GET_ITEM: _get_item,
    McpTool.CREATE_ITEM: _create_item,
    McpTool.UPDATE_ITEM: _update_item,
    McpTool.COMMENT_ITEM: _comment_item,
    McpTool.LIST_PROJECTS: _list_projects,
    McpTool.GET_DOC_PAGE: _get_doc_page,
    McpTool.SEARCH_DOCS: _search_docs,
}


async def call_tool(
    session: AsyncSession, actor: User, name: str, arguments: Mapping[str, Any]
) -> Any:
    """Dispatch one tools/call. Raises UnknownToolError for names outside the
    (currently available) catalog; RaddError subclasses bubble up for the router
    to shape into `isError: true` results."""
    try:
        tool = McpTool(name)
    except ValueError:
        raise UnknownToolError(name) from None
    if tool in DOC_TOOLS and not docs_bridge.docs_available():
        raise UnknownToolError(name)
    return await _HANDLERS[tool](session, actor, arguments)
