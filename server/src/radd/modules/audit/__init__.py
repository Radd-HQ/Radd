from radd.kernel import NavItemSpec, PluginUiManifest, RaddPlugin

from .mcptool import AUDIT_LOG
from .router import router

plugin = RaddPlugin(
    name="audit",
    ui=PluginUiManifest(
        nav=(NavItemSpec(
            key="audit", label="Audit log", path="/settings/audit", section="settings",
            group="Server", icon="ScrollText", order=190,
            requires_any_project=("project.manage",),
        ),),
    ),
    description=(
        "The audit log: who changed what, from what, to what — searchable by project, person, field and date."
    ),
    depends_on=("events", "auth", "projects", "items"),
    routers=(router,),
    # RADD-1172: the same ledger over MCP, enforced by the kernel dispatcher.
    mcp_tools=(AUDIT_LOG,),
)
