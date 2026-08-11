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
    crud_resources=(CrudResourceSpec("sla", "global", "SLA policies", "global.manage"),),
    core=False,  # optional plugin — disableable via the plugin manager
    description="SLA policies + timers (specs 30/63): first-match policy "
    "resolution (priority + issue-type filters, position order), "
    "response/resolution targets computed from the event-log state timeline, "
    "pause states, business-hours windows (holidays pause the clock through the "
    "kernel's non-working-days socket), breach events, and the list/board batch "
    "endpoint.",
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
    ),
    routers=(router,),
    on_startup=(engine.start,),
    on_shutdown=(engine.stop,),
    event_types=(
        EventTypeSpec(SlaEvent.BREACHED, "SLA breached", "Items", item_scoped=True),
        EventTypeSpec(SlaEvent.DUE_SOON, "SLA due soon", "Service desk", item_scoped=True),
    ),
)
