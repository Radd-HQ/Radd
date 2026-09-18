"""Related links over MCP (RADD-1239, public report radd-hq/radd#11).

The item view's "Related links" panel — a merge request, a design doc, a
monitoring page — was REST-only, so an agent that had to attach a URL fell
back to pasting it into a comment, and the panel stayed "No related links
yet". These tools address the item by key and a link by its URL: an agent
that just added a link holds the URL, and a removal names what it removes.

Enforcement is the router's — `item.update` on the item's project, resolved
through the item seam so per-item rules apply — re-used here verbatim via the
same service call chain. `item.update` is the spec-114 catalog floor.
"""

from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from radd.exceptions import NotFoundError
from radd.kernel.mcptools import object_schema
from radd.kernel.specs import McpToolSpec
from radd.modules.auth import authz
from radd.modules.auth.models import User
from radd.modules.auth.types import Permission
from radd.modules.items import service as items_service
from radd.modules.items.service.visibility import ensure_item_relation

from . import service
from .models import ItemWebLink
from .schemas import WebLinkCreate
from .types import WebLinkCategory, WebLinkEntity

_KEY = {"type": "string", "description": "Item key, e.g. TD-42."}
_URL = {"type": "string", "description": "The link's address (https://…).", "maxLength": 2000}


def _link(link: ItemWebLink) -> dict[str, Any]:
    return {
        "id": str(link.id),
        "url": link.url,
        "title": link.title,
        "category": link.category,
        "created_at": link.created_at.isoformat(),
    }


async def _writable_item(session: AsyncSession, actor: User, key: str):
    """The item, with `item.update` proven the way the REST router proves it."""
    read = await items_service.get_item_by_key(session, key, actor=actor)
    item, project, _perms = await items_service.require_readable_item(session, read.id, actor)
    permissions = await authz.require(session, actor, Permission.ITEM_UPDATE, project=project)
    await ensure_item_relation(session, actor, item, permissions, Permission.ITEM_UPDATE)
    return read


async def _list_related_links(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    read = await items_service.get_item_by_key(session, str(args["key"]), actor=actor)
    links = await service.list_for_item(session, read.id)
    return {"key": read.key, "links": [_link(link) for link in links]}


async def _add_related_link(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    read = await _writable_item(session, actor, str(args["key"]))
    data = WebLinkCreate(
        url=str(args["url"]),
        title=str(args.get("title") or ""),
        category=WebLinkCategory(str(args.get("category") or WebLinkCategory.EXTERNAL)),
    )
    link = await service.create_web_link(session, read.id, data, actor_id=actor.id)
    return {"key": read.key, "added": _link(link)}


async def _remove_related_link(session: AsyncSession, actor: User, args: Mapping[str, Any]) -> Any:
    read = await _writable_item(session, actor, str(args["key"]))
    wanted = str(args["url"]).strip()
    match = next(
        (link for link in await service.list_for_item(session, read.id) if link.url.strip() == wanted),
        None,
    )
    if match is None:
        raise NotFoundError(WebLinkEntity.WEB_LINK, wanted)
    removed = _link(match)
    await service.delete_web_link(session, match.id, actor_id=actor.id)
    return {"key": read.key, "removed": removed}


LIST_RELATED_LINKS = McpToolSpec(
    name="list_related_links",
    description="The external URLs attached to an item — what the item view shows "
    "under Related links (merge requests, docs, dashboards). Item-to-item "
    "dependencies are a different thing: see link_items.",
    input_schema=object_schema({"key": _KEY}, ["key"]),
    handler=_list_related_links,
    permission=Permission.ITEM_READ,
    project_scoped=True,
    kernel_enforced=False,
)

ADD_RELATED_LINK = McpToolSpec(
    name="add_related_link",
    description="Attach an external URL to an item so it appears under Related "
    "links, with an optional title and category.",
    input_schema=object_schema(
        {
            "key": _KEY,
            "url": _URL,
            "title": {"type": "string", "description": "Display text; defaults to the URL.", "maxLength": 300},
            "category": {
                "type": "string",
                "enum": [c.value for c in WebLinkCategory],
                "description": "Defaults to external.",
            },
        },
        ["key", "url"],
    ),
    handler=_add_related_link,
    permission=Permission.ITEM_UPDATE,
    project_scoped=True,
    kernel_enforced=False,
)

REMOVE_RELATED_LINK = McpToolSpec(
    name="remove_related_link",
    description="Remove a related link from an item, by its URL.",
    input_schema=object_schema({"key": _KEY, "url": _URL}, ["key", "url"]),
    handler=_remove_related_link,
    permission=Permission.ITEM_UPDATE,
    project_scoped=True,
    kernel_enforced=False,
)

MCP_TOOLS = (LIST_RELATED_LINKS, ADD_RELATED_LINK, REMOVE_RELATED_LINK)
