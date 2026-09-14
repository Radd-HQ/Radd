from radd.kernel import RaddPlugin

from .mcptool import AUDIT_LOG
from .router import router

plugin = RaddPlugin(
    name="audit",
    description=(
        "The audit ledger (spec 123): a read-only, filterable, searchable view over the "
        "append-only event log — who changed what, from what, to what — for instance "
        "admins and, per project, its managers. No tables — the events outbox IS the log."
    ),
    depends_on=("events", "auth", "projects", "items"),
    routers=(router,),
    # RADD-1172: the same ledger over MCP, enforced by the kernel dispatcher.
    mcp_tools=(AUDIT_LOG,),
)
