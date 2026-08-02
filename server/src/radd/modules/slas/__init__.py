from radd.kernel import EventTypeSpec
from radd.kernel import RaddPlugin

from . import engine
from .router import router
from .types import SlaEvent

plugin = RaddPlugin(
    name="slas",
    core=False,  # optional plugin — disableable via the plugin manager
    description="SLA policies + timers (specs 30/63): first-match policy "
    "resolution (priority filters, position order), response/resolution targets "
    "computed from the event-log state timeline, pause states, business-hours "
    "windows, breach events, and the list/board batch endpoint.",
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
