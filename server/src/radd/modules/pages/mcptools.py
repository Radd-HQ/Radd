"""The page MCP tools, declared by their owner (RADD-889) — the kernel registry
removes them from catalog and dispatch when pages is disabled.

Every handler enforces in-handler through the REST gates (`guard_page`, or
`page.write` in the target space for a create); `permission` is only the
catalog filter (`kernel_enforced=False`). Writes answer with a receipt, never
the body (RADD-861).
"""

import uuid
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from radd.config import settings
from radd.mailrender import page_url
from radd.kernel.mcptools import limit_arg, limit_property, object_schema
from radd.kernel.specs import McpToolSpec
from radd.modules.auth import authz
from radd.modules.auth.models import User
from radd.modules.auth.types import Permission

from . import page_access, service as pages_service, spaces
from .models import Page
from .schemas import PageCreate, PageUpdate


def jsonable(value: Any) -> Any:
    """Best-effort JSON projection of whatever the pages service returns."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "__table__"):  # SQLAlchemy row
        return {c.name: jsonable(getattr(value, c.name)) for c in value.__table__.columns}
    return str(value)  # uuid, datetime, enums, ...


def receipt(page: Page) -> dict[str, Any]:
    """What a write answers with: enough to address the page again and to see
    the edit landed (the version moved), never the body."""
    return {
        "id": str(page.id),
        "number": page.number,
        "slug": page.slug,
        "title": page.title,
        "version": page.version,
        "parent_id": str(page.parent_id) if page.parent_id else None,
        # RADD-1240: a permalink to hand a person — an agent given only an id
        # assembled `/pages/<uuid>`, which is not an address.
        "url": page_url(settings.app_base_url, page.number),
    }


def _optional_uuid(value: Any) -> uuid.UUID | None:
    return uuid.UUID(str(value)) if value is not None else None


# --- handlers ---


async def _get_page(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    page = await page_access.guard_page(session, actor, uuid.UUID(str(args["id"])), Permission.PAGE_READ)
    return jsonable(page)


async def _search_pages(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    from .search_source import readable_results

    return jsonable(await readable_results(session, actor, str(args["query"]), limit=limit_arg(args)))


async def _create_page(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    space = await spaces.by_slug_or_id(session, str(args["space"]))
    await authz.require(session, actor, Permission.PAGE_WRITE, space_id=space.id)
    page = await pages_service.create_page(
        session,
        PageCreate(
            space_id=space.id,
            parent_id=_optional_uuid(args.get("parent_id")),
            title=str(args["title"]),
            body=str(args.get("body", "")),
            template=args.get("template"),
        ),
        actor.id,
    )
    return receipt(page)


async def _update_page(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    page_id = uuid.UUID(str(args["id"]))
    await page_access.guard_page(session, actor, page_id, Permission.PAGE_WRITE)
    page = await pages_service.update_page(
        session,
        page_id,
        PageUpdate(**{key: args[key] for key in ("title", "body", "expected_version") if key in args}),
        actor.id,
    )
    return receipt(page)


async def _move_page(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    """`parent_id` rides pydantic's model_fields_set: present-and-null moves to
    the root, absent leaves the parent alone (a pure reposition). The service
    carries the cross-space and cycle guards."""
    page_id = uuid.UUID(str(args["id"]))
    await page_access.guard_page(session, actor, page_id, Permission.PAGE_WRITE)
    values: dict[str, Any] = {}
    if "parent_id" in args:
        values["parent_id"] = _optional_uuid(args["parent_id"])
    if args.get("position") is not None:
        values["position"] = float(args["position"])
    page = await pages_service.update_page(session, page_id, PageUpdate(**values), actor.id)
    return receipt(page)


# --- the specs ---

_PAGE_ID = {"type": "string", "description": "Page id (UUID)."}

GET_PAGE = McpToolSpec(
    name="get_page",
    description="Fetch one wiki page by id (full markdown body).",
    input_schema=object_schema({"id": _PAGE_ID}, ["id"]),
    handler=_get_page,
    permission=Permission.PAGE_READ,
    space_scoped=True,
    kernel_enforced=False,
)

SEARCH_PAGES = McpToolSpec(
    name="search_pages",
    description="Full-text search over wiki pages (title + body), ranked.",
    input_schema=object_schema(
        {
            "query": {"type": "string", "description": "Search terms."},
            "limit": limit_property(),
        },
        ["query"],
    ),
    handler=_search_pages,
    permission=Permission.PAGE_READ,
    space_scoped=True,
    kernel_enforced=False,
)

CREATE_PAGE = McpToolSpec(
    name="create_page",
    description="Create a wiki page in a space. Answers with a receipt "
    "(id, number, slug, title, version, parent_id), not the body.",
    input_schema=object_schema(
        {
            "space": {"type": "string", "description": "Space SLUG (or id)."},
            "title": {"type": "string", "minLength": 1, "maxLength": 500},
            "body": {"type": "string", "description": "Markdown body.", "default": ""},
            "parent_id": {
                "type": ["string", "null"],
                "description": "Parent page id (UUID) in the same space; omit for a root page.",
            },
            "template": {
                "type": ["string", "null"],
                "description": "Page template NAME to start from; ignored when body is given.",
            },
        },
        ["space", "title"],
    ),
    handler=_create_page,
    permission=Permission.PAGE_WRITE,
    space_scoped=True,
    kernel_enforced=False,
)

UPDATE_PAGE = McpToolSpec(
    name="update_page",
    description="Edit a wiki page's title and/or markdown body (a new version). "
    "Pass expected_version to refuse clobbering a concurrent edit.",
    input_schema=object_schema(
        {
            "id": _PAGE_ID,
            "title": {"type": "string", "minLength": 1, "maxLength": 500},
            "body": {"type": "string", "description": "Full replacement markdown body."},
            "expected_version": {
                "type": "integer",
                "minimum": 1,
                "description": "The version you read; a mismatch is a conflict.",
            },
        },
        ["id"],
    ),
    handler=_update_page,
    permission=Permission.PAGE_WRITE,
    space_scoped=True,
    kernel_enforced=False,
)

MOVE_PAGE = McpToolSpec(
    name="move_page",
    description="Move a wiki page under another page (null parent_id = the space "
    "root) and/or reorder it among its siblings. Same space only; cycles refused.",
    input_schema=object_schema(
        {
            "id": _PAGE_ID,
            "parent_id": {
                "type": ["string", "null"],
                "description": "New parent page id (UUID); null moves to the root; "
                "omit to only reposition.",
            },
            "position": {"type": "number", "description": "Sort position among siblings."},
        },
        ["id"],
    ),
    handler=_move_page,
    permission=Permission.PAGE_WRITE,
    space_scoped=True,
    kernel_enforced=False,
)

MCP_TOOLS = (GET_PAGE, SEARCH_PAGES, CREATE_PAGE, UPDATE_PAGE, MOVE_PAGE)
