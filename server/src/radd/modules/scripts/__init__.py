"""scripts — admin-authored Python run from automations (RADD-1269), optional.
A uv-built interpreter plus two nodes, `script.run` and `script.decide`; the body
lives on the node, so the graph's versions are its history. Runs OUT OF PROCESS
with a short-lived key for the automation's identity."""

from radd.kernel import NavItemSpec, EventTypeSpec, PermissionSpec, PluginUiManifest, RaddPlugin

from .nodes import DECIDE_NODE, RUN_NODE
from .router import router
from .types import PERM_MANAGE, ScriptEvent

plugin = RaddPlugin(
    # The node inspectors ship in this remote (`automation.node.inspector`).
    ui=PluginUiManifest(
        remote="/plugins/scripts/remoteEntry.js", ui_api_version="2.0.0",
        nav=(NavItemSpec(key="scripts", label="Scripts", path="/settings/scripts",
                         section="settings", group="Server", icon="terminal", order=95,
                         requires=(PERM_MANAGE,)),),
    ),
    name="scripts",
    id="radd.scripts",
    version="1.0.0",
    core=False,
    description="Python scripts that automations can run, with their own packages.",
    depends_on=("auth", "events", "projects", "items"),
    routers=(router,),
    event_types=(
        EventTypeSpec(
            ScriptEvent.PACKAGE_INSTALLED, "Script package installed", "Admin",
            trigger=False, entity_type="script_package",
        ),
        EventTypeSpec(
            ScriptEvent.PACKAGE_REMOVED, "Script package removed", "Admin",
            trigger=False, entity_type="script_package",
        ),
        EventTypeSpec(
            ScriptEvent.INTERPRETER_REBUILT, "Script interpreter rebuilt", "Admin",
            trigger=False, entity_type="script_interpreter",
        ),
        EventTypeSpec(
            ScriptEvent.INTERPRETER_UPDATED, "Script package index changed", "Admin",
            has_changes=True, trigger=False, entity_type="script_interpreter",
        ),
    ),
    permissions=(
        PermissionSpec(
            PERM_MANAGE,
            "global",
            "Manage the script interpreter and its packages, write scripts, and place "
            "script nodes in automations. Scripts run arbitrary code as the automation's "
            "identity, so this is administrator territory.",
            implied_by=("global.manage",),
        ),
    ),
    automation_nodes=(RUN_NODE, DECIDE_NODE),
)
