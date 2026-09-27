from radd.kernel import EventTypeSpec, IntegrationSpec, PluginUiManifest, WidgetTypeSpec
from radd.kernel import RaddPlugin
from radd.kernel.sockets import Socket

from .gate import ApprovalGate
from .router import router
from .service import has_pending
from .types import ApprovalCheck, ApprovalEvent, ApprovalWidget

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
    # RADD-1393: "Awaiting my approval" on My Work is this plugin's contribution — a
    # personal widget type, suggested to whoever has something to decide — drawn by the
    # remote's dashboard.widget slot. Disabling approvals withdraws the type and the slot.
    widget_types=(
        WidgetTypeSpec(
            key=ApprovalWidget.AWAITING.value,
            label="Awaiting my approval",
            personal=True,
            suggest=has_pending,
        ),
    ),
    # Federated UI (spec 94): the Approvals card in the issue rail (issue.panel.section),
    # the approver editor on the workflow transitions editor (RADD-1383, the slot
    # workflow's UI package publishes in transition-rule-contract.ts), and the My Work
    # widget. 1.15.0: it links and peeks items through the SDK's host bridge.
    ui=PluginUiManifest(remote="/plugins/approvals/remoteEntry.js", ui_api_version="2.0.0"),
)
