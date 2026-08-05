from radd.kernel import EventTypeSpec
from radd.kernel import RaddPlugin

from .router import router
from .types import ReleaseEvent

# After the router chain on purpose: mcptools joins the loaded graph (RADD-889).
from . import mcptools

plugin = RaddPlugin(
    name="releases",
    description=(
        "Project-scoped releases/versions. Ordinary API resources a CI service-account "
        "or the automations engine can POST to and assign — replaces the CI-writes-labels hack."
    ),
    depends_on=("projects", "auth", "events", "settings", "workflow"),
    weak_depends=("automations", "items"),
    routers=(router,),
    # RADD-889: the release tools of the spec-114 MCP catalog live with their owner.
    mcp_tools=mcptools.MCP_TOOLS,
    event_types=(
        EventTypeSpec(ReleaseEvent.CREATED, "Release created", "Releases"),
        EventTypeSpec(ReleaseEvent.UPDATED, "Release updated", "Releases"),
        EventTypeSpec(ReleaseEvent.DELETED, "Release deleted", "Releases"),
    ),
)
