"""scripts — admin-authored Python, run from automations (RADD-1269).

A `core=False` plugin: on by default, disableable from the plugin manager. It
owns a managed interpreter (a uv-built venv with the Radd SDK client and the
packages an admin asks for), a script library with versions, and two
automation nodes — `script.run` (an action whose returned dict becomes tokens)
and `script.decide` (a gate that takes the port the script names). Scripts
run OUT OF PROCESS with a short-lived key minted for the automation's
identity, so a script can never exceed what the automation may already do.
"""

from radd.kernel import EventTypeSpec, PermissionSpec, RaddPlugin

from .nodes import DECIDE_NODE, RUN_NODE
from .router import router
from .types import PERM_MANAGE, ScriptEvent

plugin = RaddPlugin(
    name="scripts",
    id="radd.scripts",
    version="1.0.0",
    core=False,
    description="Run admin-authored Python from automations, in a managed interpreter with its own packages.",
    depends_on=("auth", "events", "projects", "items"),
    routers=(router,),
    event_types=(
        EventTypeSpec(ScriptEvent.CREATED, "Script created", "Admin", trigger=False, entity_type="script"),
        EventTypeSpec(
            ScriptEvent.UPDATED, "Script updated", "Admin", has_changes=True, trigger=False, entity_type="script"
        ),
        EventTypeSpec(ScriptEvent.DELETED, "Script deleted", "Admin", trigger=False, entity_type="script"),
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
