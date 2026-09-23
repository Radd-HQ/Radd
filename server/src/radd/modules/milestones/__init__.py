"""milestones — the north-star plugin (docs/plugin-platform.md §1).

A whole feature from one directory: declare the `milestone` entity + a nav item.
The kernel auto-wires the table, CRUD endpoints (`/api/v1/milestones`), the
`milestone.created/updated/deleted` events (which surface as automation triggers,
webhook events, and audit entries), and the `milestone.create/update/delete` RBAC
atoms (which appear in the roles matrix) — with ZERO edits to any other plugin or
the kernel. This plugin is `core=False`: the plugin manager can disable it.
"""

from radd.sdk import NavItemSpec, PluginUiManifest, RaddPlugin

from .automation import SPEC as SET_STATUS_NODE
from .mcptool import LIST_MILESTONES
from .spec import SPEC

plugin = RaddPlugin(
    name="milestones",
    id="radd.milestones",
    version="1.0.0",
    core=False,
    description="Milestones with a due date per project — an example plugin.",
    depends_on=("projects", "auth", "events"),
    entities=(SPEC,),
    mcp_tools=(LIST_MILESTONES,),
    # RADD-923: the plugin contributes the ACTION that responds to its own
    # auto-wired events — the other half of the north-star. No edits to
    # `automations`, the kernel or the SPA.
    automation_nodes=(SET_STATUS_NODE,),  # RADD-640: agents see milestones too, kernel-filtered
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
        # The Milestones CRUD page ships as this plugin's federated remote (web/remotes/milestones),
        # mounted by the host at /milestones via the route.page slot (spec 94).
        remote="/plugins/milestones/remoteEntry.js",
        ui_api_version="1.0.0",
    ),
)
