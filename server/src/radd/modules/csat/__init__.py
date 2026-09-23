from radd.kernel import EventTypeSpec, PluginUiManifest
from radd.kernel import RaddPlugin
from radd.kernel import SettingSpec

from . import dispatcher
from .public_router import router as public_router
from .router import router
from .types import CsatEvent, CONSUMER_NAME

plugin = RaddPlugin(
    name="csat",
    consumer_names=(CONSUMER_NAME,),
    core=False,  # optional plugin — disableable via the plugin manager
    description="Customer satisfaction surveys emailed to requesters when their issue is resolved.",
    depends_on=("projects", "auth", "items", "settings", "events", "mailintake", "workflow"),
    # RADD-891: the sender's per-project opt-in — moved off `settings.types`'s
    # old hardcoded dict.
    settings_keys=(
        SettingSpec(
            key="csat_enabled",
            type="bool",
            scopes=("instance", "project"),
            label="CSAT surveys",
            description=(
                "Email the requester a one-click satisfaction survey when their issue is resolved. Off by default; turn it on for service-desk projects."
            ),
            section="sla",
        ),
    ),
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
