from radd.kernel import EventTypeSpec
from radd.kernel import RaddPlugin
from radd.kernel import CrudResourceSpec

from . import engine
from .router import router
from .types import SlaEvent

plugin = RaddPlugin(
    name="slas",
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
    routers=(router,),
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
    ),
)
