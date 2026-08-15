from .types import CONSUMER_NAME
from radd.kernel import RaddPlugin

from . import dispatcher
from .router import router

# After the router chain on purpose: mcptools joins the loaded graph (RADD-889).
from . import mcptools

plugin = RaddPlugin(
    name="search",
    consumer_names=(CONSUMER_NAME,),
    description="Postgres full-text search over items (key/title/description/public "
    "comments), maintained by an outbox indexer; GET /search for the palette + "
    "GET /search/deflect for KB deflection (spec 66 — docs is a deferred, "
    "feature-detected seam: it loads after search).",
    depends_on=("events", "projects", "auth", "workflow", "items", "comments", "access", "fields", "teams"),
    weak_depends=("ai", "pages"),
    routers=(router,),
    # RADD-889: find_items (the spec-103 meaning search) lives with its owner.
    mcp_tools=mcptools.MCP_TOOLS,
    on_startup=(dispatcher.start,),
    on_shutdown=(dispatcher.stop,),
)
