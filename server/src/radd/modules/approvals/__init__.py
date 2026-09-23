from radd.kernel import EventTypeSpec, PluginUiManifest
from radd.kernel import RaddPlugin

from .router import router
from .types import ApprovalEvent

plugin = RaddPlugin(
    name="approvals",
    core=False,  # optional plugin — disableable via the plugin manager
    description=(
        "Approvals on workflow transitions: a move can wait for named people or team members to approve it."
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
