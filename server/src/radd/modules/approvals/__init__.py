from radd.kernel import EventTypeSpec, IntegrationSpec, PluginUiManifest
from radd.kernel import RaddPlugin
from radd.kernel.sockets import Socket

from .gate import ApprovalGate
from .router import router
from .types import ApprovalCheck, ApprovalEvent

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
    # RADD-1383: `require_approval` is this plugin's check, served on the kernel
    # socket workflow evaluates through — so disabling approvals withdraws it,
    # and workflow fails the rules it served closed instead of calling in here.
    integrations=(
        IntegrationSpec(
            Socket.TRANSITION_CHECK, ApprovalCheck.REQUIRE_APPROVAL.value, impl=ApprovalGate()
        ),
    ),
    # Federated UI (spec 94): the Approvals card in the issue rail (issue.panel.section)
    # and the approver editor on the workflow transitions editor (RADD-1383, the slot
    # workflow's UI package publishes in transition-rule-contract.ts).
    ui=PluginUiManifest(remote="/plugins/approvals/remoteEntry.js", ui_api_version="1.0.0"),
)
