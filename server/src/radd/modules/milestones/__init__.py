"""milestones — the north-star plugin (docs/plugin-platform.md §1).

A whole feature from one directory: declare the `milestone` entity + a nav item.
The kernel auto-wires the table, CRUD endpoints (`/api/v1/milestones`), the
`milestone.created/updated/deleted` events (which surface as automation triggers,
webhook events, and audit entries), and the `milestone.create/update/delete` RBAC
atoms (which appear in the roles matrix) — with ZERO edits to any other plugin or
the kernel. This plugin is `core=False`: the plugin manager can disable it.
"""

from radd.sdk import NavItemSpec, PluginUiManifest, RaddPlugin

from .spec import SPEC

plugin = RaddPlugin(
    name="milestones",
    id="radd.milestones",
    version="1.0.0",
    core=False,
    description="Project milestones — the plugin-platform north-star (entity + nav, all auto-wired).",
    depends_on=("projects", "auth", "events"),
    entities=(SPEC,),
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
