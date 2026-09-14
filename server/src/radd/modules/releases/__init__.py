from radd.kernel import EventTypeSpec
from radd.kernel import RaddPlugin
from radd.kernel import CrudResourceSpec, ProjectPurgeSpec
from radd.kernel import SettingSpec

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
        "Project-scoped releases/versions. Ordinary API resources a CI service-account "
        "or the automations engine can POST to and assign — replaces the CI-writes-labels hack."
    ),
    depends_on=("projects", "auth", "events", "settings", "workflow"),
    weak_depends=("automations", "items"),
    # RADD-891: the pipeline's two state names — moved off `settings.types`'s
    # old hardcoded dict.
    settings_keys=(
        # State NAMES, not ids: a project's states are per-project rows, and a
        # name is what an admin sees in the picker. Resolution is by name
        # within the project, so a renamed state is a settings edit, not a
        # broken pipeline.
        SettingSpec(
            key="release_waiting_state",
            type="string",
            scopes=("instance", "project"),
            label="Waiting-for-release state",
            description=(
                "The state a merged pull request moves work to: complete, not yet shipped. "
                "Belongs to the DONE category, so throughput counts the day the work was "
                "finished rather than the day someone cut a tag. Empty turns the pipeline off."
            ),
            section="releases",
        ),
        SettingSpec(
            key="release_shipped_state",
            type="string",
            scopes=("instance", "project"),
            label="Shipped state",
            description=(
                "Where the release sweep moves waiting work when a version is published, "
                "with the release recorded on each item. Empty turns the sweep off."
            ),
            section="releases",
        ),
    ),
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
