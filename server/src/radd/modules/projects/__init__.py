from radd.kernel import EventTypeSpec
from radd.kernel import RaddPlugin

from .router import instance_router, project_router
from .types import ProjectEvent

# After the router chain on purpose: mcptools joins the loaded graph (RADD-889).
from . import mcptools

plugin = RaddPlugin(
    name="projects",
    description="Projects: global containers, keys, per-project item numbering.",
    depends_on=("events",),
    weak_depends=("auth", "settings"),
    routers=(project_router, instance_router),
    # RADD-889: list_projects of the spec-45 MCP catalog lives with its owner.
    mcp_tools=mcptools.MCP_TOOLS,
    event_types=(
        EventTypeSpec(ProjectEvent.PROJECT_CREATED, "Project created", "Admin"),
    ),
)
