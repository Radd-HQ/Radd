from radd.kernel import EventTypeSpec
from radd.kernel import RaddPlugin

from . import mcptools
from .router import router
from .types import WebLinkEvent

plugin = RaddPlugin(
    name="weblinks",
    description="Related links on issues: docs, designs and other references.",
    depends_on=("projects", "auth", "events", "items"),
    routers=(router,),
    # RADD-1239: the Related links panel over MCP (list/add/remove by URL).
    mcp_tools=mcptools.MCP_TOOLS,
    event_types=(
        EventTypeSpec(WebLinkEvent.CREATED, "Web link added", "Links", item_scoped=True),
        EventTypeSpec(
            WebLinkEvent.UPDATED, "Web link edited", "Links", item_scoped=True, has_changes=True
        ),
        EventTypeSpec(WebLinkEvent.DELETED, "Web link removed", "Links", item_scoped=True),
    ),
)
