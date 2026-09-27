from radd.kernel import EntityLinkSpec
from radd.kernel import EventTypeSpec
from radd.kernel import NavItemSpec
from radd.kernel import NavSection
from radd.kernel import PluginUiManifest
from radd.kernel import RaddPlugin
from radd.kernel import CrudResourceSpec
from radd.kernel import ViewListSpec
from radd.kernel import ViewTypeSpec
from radd.modules.auth.types import Permission

from . import engine
from .router import router
from .types import (
    QUEUE_COLUMNS,
    QUEUE_REFRESH_SECONDS,
    QUEUE_ROWS_PATH,
    SETTINGS_PAGE_SEGMENT,
    SlaEvent,
    SlaViewType,
)

plugin = RaddPlugin(
    name="slas",
    entity_links=(
        EntityLinkSpec('sla_policy', (f'/p/{{project.key}}/settings/{SETTINGS_PAGE_SEGMENT}',)),
    ),
    # Policy reads ride item.read (RADD-816); writes are project-scoped under
    # project.manage (RADD-1303).
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
    # UI: the timers (rail section, `slas.timer` column/card cell), the report, the
    # project settings page and the `slas.queue` view type.
    ui=PluginUiManifest(
        nav=(
            NavItemSpec(
                key="sla", label="SLAs", path=SETTINGS_PAGE_SEGMENT, icon="timer",
                section=NavSection.PROJECT_SETTINGS, order=70,
                # RADD-1303: a project's Manager manages its SLAs — checked in THAT project.
                requires=(Permission.SLA_UPDATE,),
            ),
        ),
        remote="/plugins/slas/remoteEntry.js",
        ui_api_version="2.0.0",
    ),
    view_types=(
        ViewTypeSpec(
            key=SlaViewType.QUEUE, label="Queue (triage list)", icon="list-ordered",
            sidebar_section="Queues",
            list_surface=ViewListSpec(
                rows_path=QUEUE_ROWS_PATH, columns=QUEUE_COLUMNS,
                refresh_seconds=QUEUE_REFRESH_SECONDS,
            ),
        ),
    ),
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
