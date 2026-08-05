"""The `find_items` MCP tool (spec 103), declared by its owner (RADD-889).

Moved verbatim from mcp/tools.py. `search_items` (structured SLQ) stays with
items; this is the text/MEANING tool, and its handler is a straight call into
`search.service.search` — which is why search owns it. Enforcement is the
search service's own project scoping, so `kernel_enforced=False` (the spec-114
`permission` drives the caller filter only).
"""

from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from radd.kernel.mcptools import limit_arg, limit_property, object_schema
from radd.kernel.specs import McpToolSpec
from radd.modules.auth.models import User
from radd.modules.auth.types import Permission

from . import service as search_service


async def _find_items(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    """Hybrid text search (spec 103): routes through search.service.search, so
    every MCP client inherits FTS+vector fusion — and any future ranking
    upgrade — with no client-side change."""
    hits = await search_service.search(
        session, actor, str(args["query"]), limit=limit_arg(args)
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


FIND_ITEMS = McpToolSpec(
    name="find_items",
    description="Find work items by text MEANING, not just keywords: hybrid "
    "full-text + semantic retrieval (when the instance has semantic search "
    "configured; plain full-text otherwise). Use this for 'issues about X' "
    "questions; use search_items with SLQ for structured filters.",
    input_schema=object_schema(
        {
            "query": {
                "type": "string",
                "description": "Plain-language description of what to find.",
            },
            "limit": limit_property(),
        },
        ["query"],
    ),
    handler=_find_items,
    permission=Permission.ITEM_READ,
    project_scoped=True,
    kernel_enforced=False,
)

MCP_TOOLS = (FIND_ITEMS,)
