from radd.kernel import EntityLinkSpec
from radd.kernel import EventTypeSpec
from radd.kernel import PluginUiManifest
from radd.kernel import RaddPlugin
from radd.kernel import CrudResourceSpec

from . import engine
from .router import router
from .types import SlaEvent

plugin = RaddPlugin(
    name="slas",
    entity_links=(
        EntityLinkSpec('sla_policy', ('/p/{project.key}/settings/sla',)),
    ),
    # RADD-816: no sla.read — policy reads ride the project's item.read (the list is
    # project-scoped), and a minted-but-unenforced atom is the dead class it deleted.
    # RADD-1303: project-scoped under project.manage — policies are per project.
    crud_resources=(CrudResourceSpec("sla", "project", "SLA policies", "project.manage"),),
    core=False,  # optional plugin — disableable via the plugin manager
    description="Service levels: response and resolution targets with timers and breach alerts.",
    depends_on=(
        "events",
        "projects",
        "auth",
        "settings",
        "workflow",
        "items",
        "comments",
        "automations",
        "reporting",
        # RADD-1299: reporter-team filter + team reply modes (effective membership).
        "teams",
    ),
    # RADD-1386: the SLA report folds CSAT ratings in while csat is loaded —
    # checked against the plugin registry per request (report.ratings).
    weak_depends=("csat",),
    routers=(router,),
    # RADD-1386: the SLA report's UI (a reports-page section and the
    # "Service desk SLA" dashboard widget) is this plugin's own remote; RADD-1394
    # added the timers — the issue rail section and the `slas.timer` list column
    # / board-card cell (an SDK 1.15 item attribute over `slas.timers`).
    ui=PluginUiManifest(remote="/plugins/slas/remoteEntry.js", ui_api_version="1.15.0"),
    on_startup=(engine.start,),
    on_shutdown=(engine.stop,),
    event_types=(
        # RADD-1168: emitted since spec 30 and never registered. Not triggers.
        EventTypeSpec(
            SlaEvent.POLICY_CREATED, "SLA policy created", "Service desk",
            subjects=("project",),
        ),
        EventTypeSpec(
            SlaEvent.POLICY_UPDATED, "SLA policy updated", "Service desk",
            has_changes=True, subjects=("project",),
        ),
        EventTypeSpec(
            SlaEvent.POLICY_DELETED, "SLA policy deleted", "Service desk",
            subjects=("project",),
        ),
        EventTypeSpec(SlaEvent.BREACHED, "SLA breached", "Items", item_scoped=True),
        EventTypeSpec(SlaEvent.DUE_SOON, "SLA due soon", "Service desk", item_scoped=True),
        EventTypeSpec(SlaEvent.MET, "SLA met", "Service desk", item_scoped=True),
    ),
)
