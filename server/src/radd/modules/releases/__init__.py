from radd.kernel import EventTypeSpec
from radd.kernel import RaddPlugin
from radd.kernel import CrudResourceSpec, ProjectPurgeSpec

from .router import router
from . import subscribers  # noqa: F401 — RADD-1174: the project-teardown hooks
from .types import ReleaseEvent

# After the router chain on purpose: mcptools joins the loaded graph (RADD-889).
from . import mcptools

plugin = RaddPlugin(
    name="releases",
    # No coarse verb of its own: the umbrella is project.manage directly.
    crud_resources=(CrudResourceSpec("release", "project", "releases", "project.manage"),),
    # RADD-892: `releases.project_id` carries no ON DELETE CASCADE. Order 30 —
    # an item's `release_id` is SET NULL, so items may still be standing.
    project_purges=(ProjectPurgeSpec(name="releases", tables=("releases",), order=30),),
    description=(
        "Releases: versions of a project, and what shipped in each."
    ),
    depends_on=("projects", "auth", "events", "workflow"),
    weak_depends=("automations", "items"),
    routers=(router,),
    # RADD-889: the release tools of the spec-114 MCP catalog live with their owner.
    mcp_tools=mcptools.MCP_TOOLS,
    event_types=(
        EventTypeSpec(ReleaseEvent.CREATED, "Release created", "Releases", subjects=("project",)),
        EventTypeSpec(
            ReleaseEvent.UPDATED, "Release updated", "Releases",
            has_changes=True, subjects=("project",),
        ),
        EventTypeSpec(ReleaseEvent.DELETED, "Release deleted", "Releases", subjects=("project",)),
    ),
)
