from .types import CONSUMER_NAME
from radd.kernel import RaddPlugin

from . import dispatcher
from .router import router
from .searchable import ITEM_SEARCHABLE

# After the router chain on purpose: mcptools joins the loaded graph (RADD-889).
from . import mcptools

plugin = RaddPlugin(
    name="search",
    consumer_names=(CONSUMER_NAME,),
    consumer_descriptions=((CONSUMER_NAME, "Keeps full-text search fresh"),),
    description="Search across issues and pages.",
    depends_on=("events", "projects", "auth", "workflow", "items", "comments", "access", "fields", "teams"),
    weak_depends=("ai", "pages"),
    routers=(router,),
    # RADD-889: find_items (the spec-103 meaning search) lives with its owner.
    mcp_tools=mcptools.MCP_TOOLS,
    # RADD-1327: issues through the same seam a plugin entity uses.
    searchables=(ITEM_SEARCHABLE,),
    on_startup=(dispatcher.start,),
    on_shutdown=(dispatcher.stop,),
)
