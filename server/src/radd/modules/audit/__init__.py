from radd.kernel import RaddPlugin

from .mcptool import AUDIT_LOG
from .router import router

plugin = RaddPlugin(
    name="audit",
    description=(
        "The audit log: who changed what, from what, to what — searchable by project, person, field and date."
    ),
    depends_on=("events", "auth", "projects", "items"),
    routers=(router,),
    # RADD-1172: the same ledger over MCP, enforced by the kernel dispatcher.
    mcp_tools=(AUDIT_LOG,),
)
