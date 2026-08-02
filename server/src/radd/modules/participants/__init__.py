from radd.kernel import EventTypeSpec, PluginUiManifest
from radd.kernel import RaddPlugin

from .router import router
from .types import ParticipantEvent

plugin = RaddPlugin(
    name="participants",
    core=False,  # optional plugin — disableable via the plugin manager
    description=(
        "Request participants (spec 72): users + whole teams following an item. "
        "A notification/visibility-lite concept riding the watcher machinery — "
        "the reporter can share their own ticket (identity check, not "
        "permission), direct users are auto-watched, team rows resolve LIVE at "
        "notify fan-out time; RBAC is never widened."
    ),
    depends_on=("events", "projects", "auth", "teams", "items", "notify"),
    routers=(router,),
    event_types=(
        EventTypeSpec(ParticipantEvent.ADDED, "Participant added", "Service desk", item_scoped=True),
        EventTypeSpec(ParticipantEvent.REMOVED, "Participant removed", "Service desk", item_scoped=True),
    ),
    # Federated UI (spec 94): the Participants card in the issue right-rail ships as this plugin's
    # own module-federation remote (web/remotes/participants), loaded at runtime — not baked into
    # the host. The host renders it through the `issue.panel.section` slot.
    ui=PluginUiManifest(remote="/plugins/participants/remoteEntry.js", ui_api_version="1.0.0"),
)
