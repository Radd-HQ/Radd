from radd.kernel import EventTypeSpec, PluginUiManifest
from radd.kernel import RaddPlugin

from . import dispatcher
from .public_router import router as public_router
from .router import router
from .types import CsatEvent

plugin = RaddPlugin(
    name="csat",
    core=False,  # optional plugin — disableable via the plugin manager
    description="CSAT satisfaction surveys (spec 65): an outbox consumer emails the "
    "requester (mail contact, else the reporter) a one-click rating survey when an "
    "item resolves in a CSAT_ENABLED project; a tokened public page records the "
    "rating, which surfaces on the item and in the service-desk report.",
    depends_on=("projects", "auth", "items", "settings", "events", "mailintake"),
    routers=(router, public_router),
    on_startup=(dispatcher.start,),
    on_shutdown=(dispatcher.stop,),
    event_types=(
        EventTypeSpec(CsatEvent.REQUESTED, "CSAT survey sent", "Service desk", item_scoped=True),
        EventTypeSpec(CsatEvent.RESPONDED, "CSAT response received", "Service desk", item_scoped=True),
    ),
    # Federated UI (spec 94): the CSAT rating chip in the issue rail (web/remotes/csat),
    # rendered by the host via the issue.panel.section slot.
    ui=PluginUiManifest(remote="/plugins/csat/remoteEntry.js", ui_api_version="1.0.0"),
)
