from radd.kernel import EntityRefSpec, EventTypeSpec, GrantScopeSpec
from radd.kernel import RaddPlugin

from . import service
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
    # RADD-923: how a project describes itself in an event payload.
    entity_refs=(EntityRefSpec("project", service.project_ref, label="Project"),),
    event_types=(
        EventTypeSpec(ProjectEvent.PROJECT_CREATED, "Project created", "Admin"),
        # RADD-1009: rename/description edits; `changes` carries the diff.
        EventTypeSpec(ProjectEvent.PROJECT_UPDATED, "Project updated", "Admin", has_changes=True),
        # RADD-1174: the row is gone; the payload names it and what went with it.
        EventTypeSpec(ProjectEvent.PROJECT_DELETED, "Project deleted", "Admin"),
    ),
    # RADD-892: what a project-scoped role grant is bound to. No `reach` — how
    # many projects someone can READ is an atom question, and auth answers it
    # with its own machinery rather than asking the scope owner.
    grant_scopes=(
        GrantScopeSpec(
            key="project",
            labels=service.project_keys,
            exists=service.project_exists,
        ),
    ),
)
