"""The page MCP tools (spec 43/45), declared by their owner (RADD-889).

This replaces mcp/pages_bridge.py — an importlib reflection bridge that probed
this module's service by function NAME so the doc tools could light up without
mcp importing pages. The kernel registry is that seam done properly: pages
contributes the specs on its manifest, so an absent or disabled pages plugin
takes the tools out of catalog AND dispatch with no feature detection at all
(the spec-94 unmount path — which the settings-modules probe never covered for
a HOT disable).

Behavior is the bridge's, verbatim: `get_page` answers the raw page row's
column projection, `search_pages` the ranked FTS results. Neither handler adds
an authz call — exactly the pre-move surface; the spec's `permission` is the
spec-114 catalog filter (`kernel_enforced=False`).
"""

import uuid
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from radd.kernel.mcptools import limit_arg, limit_property, object_schema
from radd.kernel.specs import McpToolSpec
from radd.modules.auth.models import User
from radd.modules.auth.types import Permission

from . import search as pages_search, service as pages_service


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


async def _get_page(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    page = await pages_service.get_page(session, uuid.UUID(str(args["id"])))
    return jsonable(page)


async def _search_pages(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    limit = limit_arg(args)
    # Spec 86: docs are global — a single search over every space.
    results = jsonable(await pages_search.search_pages(session, str(args["query"]), limit=limit))
    return (results if isinstance(results, list) else [results])[:limit]


GET_PAGE = McpToolSpec(
    name="get_page",
    description="Fetch one wiki page by id (full markdown body).",
    input_schema=object_schema(
        {"id": {"type": "string", "description": "Doc page id (UUID)."}}, ["id"]
    ),
    handler=_get_page,
    permission=Permission.PAGE_READ,
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
    kernel_enforced=False,
)

MCP_TOOLS = (GET_PAGE, SEARCH_PAGES)
