"""milestones — the north-star plugin (docs/plugin-platform.md §1): a whole feature
from one directory, with zero edits to any other plugin or the kernel (see
`spec.py`). `core=False`: the plugin manager can disable it."""

from radd.sdk import NavItemSpec, PluginUiManifest, RaddPlugin

from .automation import SPEC as SET_STATUS_NODE
from .mcptool import LIST_MILESTONES
from .spec import SPEC

plugin = RaddPlugin(
    name="milestones",
    id="radd.milestones",
    version="1.0.0",
    core=False,
    enabled_by_default=False,  # RADD-1290: the plugin-platform example, off on a fresh instance
    description="Milestones with a due date per project — an example plugin.",
    depends_on=("projects", "auth", "events"),
    entities=(SPEC,),
    mcp_tools=(LIST_MILESTONES,),  # RADD-640: agents see milestones too, kernel-filtered
    # RADD-923: the ACTION that responds to its own auto-wired events.
    automation_nodes=(SET_STATUS_NODE,),
    ui=PluginUiManifest(
        nav=(
            NavItemSpec(
                key="milestones",
                label="Milestones",
                path="/milestones",
                icon="flag",
                section="main",
                requires=("item.read",),
                order=55,
            ),
        ),
        # The CRUD page is this plugin's federated remote (milestones/ui), mounted at
        # /milestones via the route.page slot (spec 94).
        remote="/plugins/milestones/remoteEntry.js",
        ui_api_version="1.0.0",
    ),
)
