from radd.kernel import EventTypeSpec, PluginUiManifest
from radd.kernel import RaddPlugin

from .router import router
from .types import ApprovalEvent

plugin = RaddPlugin(
    name="approvals",
    core=False,  # optional plugin — disableable via the plugin manager
    description=(
        "JSM-style approvals on workflow transitions (spec 71): a require_approval "
        "transition rule gates state moves; this module owns the request/vote "
        "lifecycle (N-of-M, live team membership), auto-applies the move on the "
        "deciding vote, and feeds the guard through deferred seams."
    ),
    depends_on=("events", "projects", "auth", "teams", "workflow", "items"),
    routers=(router,),
    event_types=(
        EventTypeSpec(ApprovalEvent.REQUESTED, "Approval requested", "Service desk", item_scoped=True),
        EventTypeSpec(ApprovalEvent.VOTED, "Approval vote cast", "Service desk", item_scoped=True),
        EventTypeSpec(ApprovalEvent.APPROVED, "Approval granted", "Service desk", item_scoped=True),
        EventTypeSpec(ApprovalEvent.DECLINED, "Approval declined", "Service desk", item_scoped=True),
        EventTypeSpec(ApprovalEvent.CANCELED, "Approval canceled", "Service desk", item_scoped=True),
    ),
    # Federated UI (spec 94): the Approvals card in the issue rail (web/remotes/approvals),
    # rendered by the host via the issue.panel.section slot.
    ui=PluginUiManifest(remote="/plugins/approvals/remoteEntry.js", ui_api_version="1.0.0"),
)
